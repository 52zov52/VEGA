"""Тюнинг весов ансамбля: глобальные vs стратифицированные по days_since_obs.

Честная схема: fit на train-сплите, подбор весов на validation-масках
нескольких сидов (устойчивость), финальный вердикт по pooled RMSE 1d.
Ничего не пишет в models/ — только отчёт в stdout.
"""
import sys
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ml.data.contract import TARGET_COL, normalize_columns
from ml.evaluation.gaps import mask_random_gaps
from ml.evaluation.metrics import gap_score, rmse
from ml.evaluation.splits import time_forward_splits
from ml.features.build import build_features
from ml.inference.predict import predict_gaps
from ml.models.baselines import baseline_seasonal
from ml.models.ensemble import EnsembleWeights, ensemble_predict
from ml.models.residual import ResidualGBM
from ml.models.temporal import TemporalModel
from scripts.train import _truth_at, make_fit_set
from services.climatology.climatology import PastClimatology

SEED = 42
SEEDS = [42, 43, 44, 45, 46]


def grid_best(y, pg, pt, ps, step=0.05):
    best, best_w = float("inf"), EnsembleWeights(0.4, 0.2, 0.4)
    n = int(round(1 / step))
    for i, j in product(range(n + 1), repeat=2):
        a, b = i * step, j * step
        if a + b > 1 + 1e-9:
            continue
        w = EnsembleWeights(a, b, max(0.0, 1 - a - b))
        s = rmse(y, ensemble_predict(pg, pt, ps, w))
        if s < best:
            best, best_w = s, w
    return best, best_w.normalized()


def collect(valid_df, clim_train, base, gap_len, seeds):
    Y, G, T, S, D = [], [], [], [], []
    for s in seeds:
        masked = mask_random_gaps(valid_df, gap_len=gap_len, n_gaps=30, seed=s)
        if not masked["is_synthetic_gap"].any():
            continue
        sel = masked["is_synthetic_gap"].to_numpy()
        y = _truth_at(valid_df, masked)
        pg = predict_gaps(masked, {**base, "weights": EnsembleWeights(1, 0, 0)},
                          clim=clim_train).to_numpy(float)[sel]
        pt = predict_gaps(masked, {**base, "weights": EnsembleWeights(0, 1, 0)},
                          clim=clim_train).to_numpy(float)
        pt = pt[sel]
        sea = []
        for _, sub in masked.groupby("polygon_id"):
            sea += baseline_seasonal(sub)[sub["is_synthetic_gap"].to_numpy()].tolist()
        ps = np.asarray(sea, dtype=float)
        feat, _ = build_features(masked, clim=clim_train)
        dso = feat["days_since_obs"].to_numpy()[sel] if "days_since_obs" in feat else np.ones(sel.sum())
        Y.append(y); G.append(pg); T.append(pt); S.append(ps); D.append(dso)
    return (np.concatenate(Y), np.concatenate(G), np.concatenate(T),
            np.concatenate(S), np.concatenate(D))


def main():
    df = normalize_columns(pd.read_csv(ROOT / "data" / "train_dataset.csv"))
    df = df[df[TARGET_COL].notna()].copy()
    train_df, valid_df = time_forward_splits(df)[-1]
    print(f"train={len(train_df)} valid={len(valid_df)}", flush=True)
    clim_train = PastClimatology().fit(train_df)
    X_fit, y_fit, cols = make_fit_set(train_df, clim_train, SEED)
    print(f"fit_rows={len(X_fit)} cols={len(cols)}", flush=True)
    gbm = ResidualGBM(seed=SEED).fit(X_fit, y_fit)
    tmp = TemporalModel(seed=SEED).fit(X_fit, y_fit)
    print(f"backends: {gbm.used_backend} + {tmp.used_backend}", flush=True)
    base = {"gbm": gbm, "temporal": tmp, "feature_cols": cols}

    for gap_len in (1, 2, 3):
        y, pg, pt, ps, dso = collect(valid_df, clim_train, base, gap_len,
                                     SEEDS if gap_len == 1 else [42, 43, 44])
        # линейный бейзлайн считать не нужно — он уже известен из experiment_01.md
        print(f"--- gap {gap_len}d: n={len(y)} dso_med={np.median(dso):.0f} "
              f"gbm={rmse(y, pg):.4f} tmp={rmse(y, pt):.4f} sea={rmse(y, ps):.4f}", flush=True)
        bg, wg = grid_best(y, pg, pt, ps, 0.05)
        print(f"  global05: rmse={bg:.4f} score={gap_score(bg)} w=({wg.w_gbm:.2f}/{wg.w_temporal:.2f}/{wg.w_seasonal:.2f})", flush=True)
        bg2, wg2 = grid_best(y, pg, pt, ps, 0.025)
        print(f"  global025: rmse={bg2:.4f} score={gap_score(bg2)} w=({wg2.w_gbm:.3f}/{wg2.w_temporal:.3f}/{wg2.w_seasonal:.3f})", flush=True)
        # стратификация по давности наблюдения
        bins = {"dso1-2": dso <= 2, "dso3-7": (dso >= 3) & (dso <= 7), "dso8+": dso >= 8}
        pred = np.zeros_like(y)
        tot = 0
        for name, m_ in bins.items():
            if m_.sum() < 20:
                print(f"  {name}: n={m_.sum()} too small, skip", flush=True)
                pred[m_] = ensemble_predict(pg[m_], pt[m_], ps[m_], wg)
                continue
            b, w = grid_best(y[m_], pg[m_], pt[m_], ps[m_], 0.05)
            pred[m_] = ensemble_predict(pg[m_], pt[m_], ps[m_], w)
            tot += 0
            print(f"  {name}: n={m_.sum()} rmse={b:.4f} w=({w.w_gbm:.2f}/{w.w_temporal:.2f}/{w.w_seasonal:.2f})", flush=True)
        s = rmse(y, pred)
        print(f"  STRATIFIED pooled: rmse={s:.4f} score={gap_score(s)}", flush=True)


if __name__ == "__main__":
    main()
