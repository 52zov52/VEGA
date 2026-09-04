"""Обучение финального ансамбля (§28): EDA -> time-aware validation -> baselines -> ensemble.

Использование:
    python scripts/train.py --train data/train_dataset.csv --out models
    python scripts/train.py --train data/train_dataset.csv --extra data/test.csv --out models

--extra: известные (не скрытые) строки теста добавляются ТОЛЬКО в финальный
фит (валидация остаётся честной — на train-сплитах). Скрытые значения
(is_synthetic_gap / NaN target) не используются никогда.

Сохраняет models/gbm.joblib, models/temporal.joblib, models/meta.json
и пишет experiments/ensemble.csv.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ml.data.contract import TARGET_COL, normalize_columns  # noqa: E402
from ml.data.dataset import generate_demo_dataset  # noqa: E402
from ml.evaluation.gaps import mask_random_gaps  # noqa: E402
from ml.evaluation.leakage import check_no_future_features, check_temporal_order  # noqa: E402
from ml.evaluation.metrics import gap_score, rmse  # noqa: E402
from ml.evaluation.splits import time_forward_splits  # noqa: E402
from ml.features.build import FEATURES_VERSION, build_features  # noqa: E402
from ml.models.baselines import baseline_linear, baseline_nearest, baseline_seasonal  # noqa: E402
from ml.models.ensemble import EnsembleWeights, ensemble_predict, grid_search_weights  # noqa: E402
from ml.models.gbm import GBMModel  # noqa: E402
from ml.models.temporal import TemporalModel  # noqa: E402
from services.climatology.climatology import PastClimatology  # noqa: E402

SEED = int(os.getenv("TZ_SEED", "42"))
DATASET_VERSION = os.getenv("DATASET_VERSION", "v4-contest")
GAP_GRID = (1, 2, 3, 7, 14, 30)


def _truth_at(valid_known: pd.DataFrame, masked: pd.DataFrame) -> np.ndarray:
    key = masked[masked["is_synthetic_gap"]].set_index(["polygon_id", "date"]).index
    return valid_known.set_index(["polygon_id", "date"])[TARGET_COL].loc[key].to_numpy(dtype=float)


def eval_on_masked(
    valid_known: pd.DataFrame,
    gap_len: int,
    seed: int,
    models: dict,
    clim_train: PastClimatology,
) -> dict[str, float]:
    """Маскирует пропуски длины gap_len и считает RMSE каждого метода."""
    from ml.inference.predict import predict_gaps

    masked = mask_random_gaps(valid_known, gap_len=gap_len, n_gaps=30, seed=seed)
    if not masked["is_synthetic_gap"].any():
        return {}
    y_true = _truth_at(valid_known, masked)
    out: dict[str, float] = {}
    for name in ("nearest", "linear", "seasonal"):
        preds: list[float] = []
        for _, sub in masked.groupby("polygon_id"):
            s = sub.set_index("date")[TARGET_COL].astype(float)
            if name == "nearest":
                f = baseline_nearest(s)
            elif name == "linear":
                f = baseline_linear(s)
            else:
                f = pd.Series(baseline_seasonal(sub).to_numpy(), index=s.index)
            preds += f.loc[sub.set_index("date").index[sub["is_synthetic_gap"].to_numpy()]].tolist()
        out[name] = rmse(y_true, np.asarray(preds, dtype=float))
    # ML с климатологией, fitted только на train-сплите (без будущего valid).
    art = {"gbm": models["gbm"], "temporal": models["temporal"],
           "weights": EnsembleWeights(1, 0, 0), "feature_cols": models["feature_cols"]}
    p_gbm = predict_gaps(masked, art, clim=clim_train).loc[masked["is_synthetic_gap"].to_numpy()].to_numpy(float)
    p_tmp = predict_gaps(masked, {**art, "weights": EnsembleWeights(0, 1, 0)},
                         clim=clim_train).loc[masked["is_synthetic_gap"].to_numpy()].to_numpy(float)
    sea_vals: list[float] = []
    for _, sub in masked.groupby("polygon_id"):
        sea_vals += baseline_seasonal(sub)[sub["is_synthetic_gap"].to_numpy()].tolist()
    p_sea = np.asarray(sea_vals, dtype=float)
    out["gbm"] = rmse(y_true, p_gbm)
    out["temporal"] = rmse(y_true, p_tmp)
    out["ensemble"] = rmse(y_true, ensemble_predict(p_gbm, p_tmp, p_sea, models["weights"]))
    return out


def load_frame(path: str | None, fallback_demo: bool = True) -> tuple[pd.DataFrame, str]:
    if path and Path(path).exists():
        df = normalize_columns(pd.read_csv(path))
        return df, path
    if fallback_demo:
        return generate_demo_dataset(), "demo"
    return pd.DataFrame(), "empty"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", default=None)
    ap.add_argument("--extra", default=None,
                    help="CSV с известными строками (напр. data/test.csv) только для финального фита")
    ap.add_argument("--out", default="models")
    args = ap.parse_args()
    t0 = time.time()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    df, source = load_frame(args.train)
    df = df[df[TARGET_COL].notna()].copy() if TARGET_COL in df.columns else df
    print(f"dataset: {source} known_rows={len(df)} polygons={df['polygon_id'].nunique() if len(df) else 0}")
    splits = time_forward_splits(df)
    print(f"time-aware splits: {len(splits)} " +
          ", ".join(f"tr<{pd.to_datetime(v['date']).min().date()} va={pd.to_datetime(v['date']).min().date()}..{pd.to_datetime(v['date']).max().date()}" for _, v in splits))
    for tr, va in splits:
        for issue in check_temporal_order(tr, va):
            print(f"LEAKAGE WARNING: {issue}")

    # Валидация на последнем (самом полном) фолде.
    train_df, valid_df = splits[-1]
    clim_train = PastClimatology().fit(train_df)
    feat_tr, cols = build_features(train_df, clim=clim_train)
    for bad in check_no_future_features(cols):
        print(f"LEAKAGE FEATURE: {bad}")
        raise SystemExit(1)
    y_tr = feat_tr[TARGET_COL].astype(float)
    X_tr = feat_tr[cols]
    print(f"features {FEATURES_VERSION}: {len(cols)} cols, train={len(X_tr)}")

    gbm = GBMModel(seed=SEED).fit(X_tr, y_tr)
    temporal = TemporalModel(seed=SEED).fit(feat_tr, y_tr)
    print(f"backends: gbm={gbm.used_backend} temporal={temporal.used_backend}", flush=True)

    # Подбор весов на validation gaps 3 дня (ближе к структуре скрытого теста).
    from ml.inference.predict import predict_gaps as _pg

    masked_w = mask_random_gaps(valid_df, gap_len=3, n_gaps=30, seed=SEED)
    y_w = _truth_at(valid_df, masked_w)
    base = {"gbm": gbm, "temporal": temporal, "feature_cols": cols}
    p_gbm_w = _pg(masked_w, {**base, "weights": EnsembleWeights(1, 0, 0)}, clim=clim_train).loc[
        masked_w["is_synthetic_gap"].to_numpy()].to_numpy(float)
    p_tmp_w = _pg(masked_w, {**base, "weights": EnsembleWeights(0, 1, 0)}, clim=clim_train).loc[
        masked_w["is_synthetic_gap"].to_numpy()].to_numpy(float)
    sea_w: list[float] = []
    for _, sub in masked_w.groupby("polygon_id"):
        sea_w += baseline_seasonal(sub)[sub["is_synthetic_gap"].to_numpy()].tolist()
    p_sea_w = np.asarray(sea_w, dtype=float)
    weights = grid_search_weights(y_w, p_gbm_w, p_tmp_w, p_sea_w)
    print(f"weights: gbm={weights.w_gbm:.2f} temporal={weights.w_temporal:.2f} seasonal={weights.w_seasonal:.2f}")
    print(f"valid 3d RMSE: gbm={rmse(y_w, p_gbm_w):.4f} tmp={rmse(y_w, p_tmp_w):.4f} "
          f"sea={rmse(y_w, p_sea_w):.4f} ens={rmse(y_w, ensemble_predict(p_gbm_w, p_tmp_w, p_sea_w, weights)):.4f} "
          f"gap_score={gap_score(rmse(y_w, ensemble_predict(p_gbm_w, p_tmp_w, p_sea_w, weights)))}")

    models = {"gbm": gbm, "temporal": temporal, "weights": weights, "feature_cols": cols}
    table: dict[str, dict[str, float]] = {}
    for gap_len in GAP_GRID:
        r = eval_on_masked(valid_df, gap_len, SEED, models, clim_train)
        table[f"{gap_len}d"] = r
        print(f"gap {gap_len}d:", {k: round(v, 4) for k, v in r.items()}, flush=True)

    # Финальный фит на всех известных (train + extra-known из теста).
    final_df = df
    if args.extra and Path(args.extra).exists():
        extra = normalize_columns(pd.read_csv(args.extra))
        extra_known = extra[extra[TARGET_COL].notna()].copy() if TARGET_COL in extra.columns else extra
        final_df = pd.concat([df, extra_known], ignore_index=True).drop_duplicates(
            ["polygon_id", "date"], keep="last").sort_values(["polygon_id", "date"]).reset_index(drop=True)
        print(f"final fit: +{len(extra_known)} extra-known rows -> {len(final_df)}")
    clim_final = PastClimatology().fit(final_df)
    feat_f, cols_f = build_features(final_df, clim=clim_final)
    gbm_f = GBMModel(seed=SEED).fit(feat_f[cols_f], feat_f[TARGET_COL].astype(float))
    temporal_f = TemporalModel(seed=SEED).fit(feat_f, feat_f[TARGET_COL].astype(float))

    import joblib

    joblib.dump(gbm_f, out_dir / "gbm.joblib")
    joblib.dump(temporal_f, out_dir / "temporal.joblib")
    final_rmse = rmse(y_w, ensemble_predict(p_gbm_w, p_tmp_w, p_sea_w, weights))
    (out_dir / "meta.json").write_text(json.dumps({
        "seed": SEED, "dataset_version": DATASET_VERSION, "features": FEATURES_VERSION,
        "model": f"ensemble({gbm_f.used_backend}+{temporal_f.used_backend}+seasonal)",
        "split": "time_forward", "weights": vars(weights.normalized()),
        "score_valid_3d": final_rmse, "gap_score_valid_3d": gap_score(final_rmse),
        "train_time_s": round(time.time() - t0, 1),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    exp_dir = ROOT / "experiments"
    exp_dir.mkdir(exist_ok=True)
    rows = []
    for gap, res in table.items():
        for method, score in res.items():
            rows.append({"gap": gap, "method": method, "rmse": round(float(score), 5),
                         "gap_score": gap_score(float(score))})
    pd.DataFrame(rows).to_csv(exp_dir / "ensemble.csv", index=False)
    print(f"done in {time.time() - t0:.1f}s -> {out_dir}/ meta + experiments/ensemble.csv")


if __name__ == "__main__":
    main()
