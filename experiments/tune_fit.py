"""Эксперимент: увеличенный self-supervised fit-set (больше масок, есть 2d, два сида).

Схема та же честная: fit на train-сплите, замер на validation-масках
мультисида (1d/2d/3d) + стратификация. Сравнение с базой (7727 строк).
"""
import sys
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
from ml.models.ensemble import EnsembleWeights
from ml.models.residual import ResidualGBM
from ml.models.temporal import TemporalModel
from scripts.train import _truth_at, fit_rows_from_masked
from services.climatology.climatology import PastClimatology

from experiments.tune_stratified import collect, grid_best

SEED = 42


def make_fit_set_big(known_df, clim_fit, seed):
    parts_X, parts_y, cols = [], [], []
    plan = ((1, 250, seed), (2, 100, seed + 1), (3, 100, seed + 2),
            (1, 150, seed + 11), (3, 60, seed + 12))
    for gap_len, n_gaps, s in plan:
        masked = mask_random_gaps(known_df, gap_len=gap_len, n_gaps=n_gaps, seed=s)
        if not masked["is_synthetic_gap"].any():
            continue
        feat, cols = build_features(masked, clim=clim_fit)
        Xp, yp = fit_rows_from_masked(masked, known_df, feat, cols)
        parts_X.append(Xp)
        parts_y.append(yp)
    return (pd.concat(parts_X, ignore_index=True), pd.concat(parts_y, ignore_index=True), cols)


def main():
    df = normalize_columns(pd.read_csv(ROOT / "data" / "train_dataset.csv"))
    df = df[df[TARGET_COL].notna()].copy()
    train_df, valid_df = time_forward_splits(df)[-1]
    clim_train = PastClimatology().fit(train_df)

    X_fit, y_fit, cols = make_fit_set_big(train_df, clim_train, SEED)
    print(f"BIG fit_rows={len(X_fit)} cols={len(cols)}", flush=True)
    gbm = ResidualGBM(seed=SEED).fit(X_fit, y_fit)
    tmp = TemporalModel(seed=SEED).fit(X_fit, y_fit)
    print(f"backends: {gbm.used_backend} + {tmp.used_backend}", flush=True)
    base = {"gbm": gbm, "temporal": tmp, "feature_cols": cols}

    for gap_len in (1, 2, 3):
        y, pg, pt, ps, dso = collect(valid_df, clim_train, base, gap_len, [42, 43, 44, 45, 46])
        bg, wg = grid_best(y, pg, pt, ps, 0.05)
        print(f"gap {gap_len}d n={len(y)}: gbm={rmse(y, pg):.4f} tmp={rmse(y, pt):.4f} "
              f"sea={rmse(y, ps):.4f} GLOBAL={bg:.4f} (score {gap_score(bg)}) "
              f"w=({wg.w_gbm:.2f}/{wg.w_temporal:.2f}/{wg.w_seasonal:.2f})", flush=True)
        bins = {"dso1-2": dso <= 2, "dso3-7": (dso >= 3) & (dso <= 7), "dso8+": dso >= 8}
        pred = np.zeros_like(y)
        for name, m_ in bins.items():
            w = wg if m_.sum() < 20 else grid_best(y[m_], pg[m_], pt[m_], ps[m_], 0.05)[1]
            from ml.models.ensemble import ensemble_predict
            pred[m_] = ensemble_predict(pg[m_], pt[m_], ps[m_], w)
        s = rmse(y, pred)
        print(f"  STRATIFIED: {s:.4f} (score {gap_score(s)})", flush=True)


if __name__ == "__main__":
    main()
