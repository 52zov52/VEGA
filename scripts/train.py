"""Обучение финального ансамбля (§28): EDA -> validation -> baselines -> ensemble.

Использование:
    python scripts/train.py --train data/train_dataset.csv --out models
    python scripts/train.py  (без файла — обучение на demo-датасете)

Сохраняет models/gbm.joblib, models/temporal.joblib, models/meta.json
и пишет experiments/*.csv + reports/experiment_*.md.
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

from ml.data.contract import TARGET_COL  # noqa: E402
from ml.data.dataset import load_train_dataset  # noqa: E402
from ml.evaluation.gaps import mask_random_gaps  # noqa: E402
from ml.evaluation.leakage import check_no_future_features, check_temporal_order  # noqa: E402
from ml.evaluation.metrics import gap_score, rmse  # noqa: E402
from ml.evaluation.splits import time_forward_splits  # noqa: E402
from ml.features.build import FEATURES_VERSION, build_features  # noqa: E402
from ml.models.baselines import baseline_linear, baseline_nearest, baseline_seasonal  # noqa: E402
from ml.models.ensemble import EnsembleWeights, ensemble_predict, grid_search_weights  # noqa: E402
from ml.models.gbm import GBMModel  # noqa: E402
from ml.models.temporal import TemporalModel  # noqa: E402

SEED = int(os.getenv("TZ_SEED", "42"))
DATASET_VERSION = os.getenv("DATASET_VERSION", "v3")


def eval_on_masked(valid_known: pd.DataFrame, gap_len: int, seed: int, models: dict) -> dict[str, float]:
    """Маскирует пропуски длины gap_len и считает RMSE каждого метода."""
    masked = mask_random_gaps(valid_known, gap_len=gap_len, n_gaps=6, seed=seed)
    truth = valid_known.set_index(["polygon_id", "date"])[TARGET_COL]
    idx = masked[masked["is_synthetic_gap"]].set_index(["polygon_id", "date"]).index
    y_true = truth.loc[idx].to_numpy(dtype=float)
    out: dict[str, float] = {}
    # Baselines — по каждому полигону отдельно, чтобы не смешивать ряды.
    for name, fn in (("nearest", None), ("linear", None), ("seasonal", None)):
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
    # ML — через преднаполненный контекст прошлого.
    from ml.inference.predict import predict_gaps

    artifacts = {"gbm": models["gbm"], "temporal": models["temporal"],
                 "weights": EnsembleWeights(1, 0, 0), "feature_cols": models["feature_cols"]}
    p_gbm_full = predict_gaps(masked, artifacts)
    artifacts["weights"] = EnsembleWeights(0, 1, 0)
    p_tmp_full = predict_gaps(masked, artifacts)
    # выравниваем по индексу синтетических пропусков
    sel = masked["is_synthetic_gap"].to_numpy()
    # predict_gaps возвращает Series в порядке masked
    p_gbm = np.asarray(p_gbm_full[sel], dtype=float)
    p_tmp = np.asarray(p_tmp_full[sel], dtype=float)
    # seasonal: берём значения из masked-групп
    sea_vals: list[float] = []
    for _, sub in masked.groupby("polygon_id"):
        f = baseline_seasonal(sub)
        sea_vals += f[sub["is_synthetic_gap"]].tolist()
    p_sea = np.asarray(sea_vals, dtype=float)
    out["catboost"] = rmse(y_true, p_gbm)
    out["tcn"] = rmse(y_true, p_tmp)
    out["seasonal_ml_check"] = rmse(y_true, p_sea)
    out["ensemble"] = rmse(y_true, ensemble_predict(p_gbm, p_tmp, p_sea, models["weights"]))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", default=None)
    ap.add_argument("--out", default="models")
    args = ap.parse_args()
    t0 = time.time()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    df, source = load_train_dataset(args.train)
    print(f"dataset: {source} rows={len(df)} polygons={df['polygon_id'].nunique()}")
    splits = time_forward_splits(df)
    print(f"time-aware splits: {len(splits)}")
    for tr, va in splits:
        for issue in check_temporal_order(tr, va):
            print(f"LEAKAGE WARNING: {issue}")

    # Обучаем на последнем (самом полном) фолде, валидируемся на его valid.
    train_df, valid_df = splits[-1]
    feat_tr, cols = build_features(train_df[train_df[TARGET_COL].notna()])
    for bad in check_no_future_features(cols):
        print(f"LEAKAGE FEATURE: {bad}")
        raise SystemExit(1)
    y_tr = feat_tr[TARGET_COL].astype(float)
    X_tr = feat_tr[cols]
    print(f"features {FEATURES_VERSION}: {len(cols)} cols, train={len(X_tr)}")

    gbm = GBMModel(seed=SEED).fit(X_tr, y_tr)
    temporal = TemporalModel(seed=SEED).fit(feat_tr, y_tr)
    print(f"backends: gbm={gbm.used_backend} temporal={temporal.used_backend}")

    # Подбор весов ансамбля на validation с синтетическими пропусками 7 дней.
    valid_known = valid_df[valid_df[TARGET_COL].notna()].copy()
    masked = mask_random_gaps(valid_known, gap_len=7, n_gaps=6, seed=SEED)
    from ml.inference.predict import predict_gaps as _pg

    tmp_art = {"gbm": gbm, "temporal": temporal, "weights": EnsembleWeights(1, 0, 0), "feature_cols": cols}
    p_gbm = _pg(masked, {**tmp_art, "weights": EnsembleWeights(1, 0, 0)}).loc[masked["is_synthetic_gap"]].to_numpy()
    p_tmp = _pg(masked, {**tmp_art, "weights": EnsembleWeights(0, 1, 0)}).loc[masked["is_synthetic_gap"]].to_numpy()
    sea_vals: list[float] = []
    for _, sub in masked.groupby("polygon_id"):
        sea_vals += baseline_seasonal(sub)[sub["is_synthetic_gap"]].tolist()
    p_sea = np.asarray(sea_vals, dtype=float)
    truth = valid_known.set_index(["polygon_id", "date"])[TARGET_COL]
    y_true = truth.loc[masked[masked["is_synthetic_gap"]].set_index(["polygon_id", "date"]).index].to_numpy(dtype=float)
    weights = grid_search_weights(y_true, p_gbm, p_tmp, p_sea)
    print(f"weights: gbm={weights.w_gbm:.2f} temporal={weights.w_temporal:.2f} seasonal={weights.w_seasonal:.2f}")

    models = {"gbm": gbm, "temporal": temporal, "weights": weights, "feature_cols": cols}
    # Таблица §12 по длинам пропусков.
    table: dict[str, dict[str, float]] = {}
    for gap_len in (1, 3, 7, 14, 30):
        r = eval_on_masked(valid_known, gap_len, SEED, models)
        table[f"{gap_len}d"] = r
        print(f"gap {gap_len}d:", {k: round(v, 4) for k, v in r.items()})
    # Сохраняем артефакты.
    import joblib

    joblib.dump(gbm, out_dir / "gbm.joblib")
    joblib.dump(temporal, out_dir / "temporal.joblib")
    (out_dir / "meta.json").write_text(json.dumps({
        "seed": SEED, "dataset_version": DATASET_VERSION, "features": FEATURES_VERSION,
        "model": f"ensemble({gbm.used_backend}+{temporal.used_backend}+seasonal)",
        "split": "time_forward", "weights": vars(weights.normalized()),
        "score": rmse(y_true, ensemble_predict(p_gbm, p_tmp, p_sea, weights)),
        "gap_score": gap_score(rmse(y_true, ensemble_predict(p_gbm, p_tmp, p_sea, weights))),
        "train_time_s": round(time.time() - t0, 1),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    # Experiments log.
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
