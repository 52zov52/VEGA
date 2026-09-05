"""Решающий эксперимент: depth8 + большой MLP + 1d-heavy fit против базы.

Замер — pooled мультисид 1d/2d/3d на validation. Порог внедрения: >=0.0015 на 1d.
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
from ml.models.ensemble import EnsembleWeights, ensemble_predict
from scripts.train import _truth_at, fit_rows_from_masked
from services.climatology.climatology import PastClimatology

from experiments.tune_stratified import collect, grid_best

SEED = 42


class BigGBM:
    used_backend = "custom-catboost-d8"

    def __init__(self, seed=42):
        self.seed = seed
        self.cols = []

    def fit(self, X, y):
        from catboost import CatBoostRegressor
        self.cols = [c for c in X.columns if c != "interp_now"]
        prior = X["interp_now"].astype(float) if "interp_now" in X.columns else 0.0
        resid = pd.Series(np.asarray(y, dtype=float), index=X.index) - pd.Series(np.asarray(prior, dtype=float), index=X.index)
        Xn = X[self.cols].fillna(X[self.cols].median(numeric_only=True)).fillna(0)
        n = len(Xn)
        cut = max(int(n * 0.9), n - 5000)
        self.model = CatBoostRegressor(iterations=3000, depth=10, learning_rate=0.015,
                                       loss_function="RMSE", random_seed=self.seed,
                                       verbose=False, early_stopping_rounds=200)
        self.model.fit(Xn.iloc[:cut], resid.iloc[:cut],
                       eval_set=(Xn.iloc[cut:], resid.iloc[cut:]))
        return self

    def predict(self, X):
        cols = [c for c in self.cols if c in X.columns]
        Xn = X[cols].fillna(0) if cols else X.fillna(0)
        prior = X["interp_now"].astype(float).to_numpy() if "interp_now" in X.columns else np.zeros(len(X))
        corr = np.asarray(self.model.predict(Xn), dtype=float)
        return np.clip(prior + corr, 0.0, 1.0)


class BigMLP:
    used_backend = "custom-mlp-128"

    def __init__(self, seed=42):
        self.seed = seed
        self.cols = []

    def _mat(self, feat):
        base = ["lag_1", "lag_2", "lag_3", "lag_7", "lag_14",
                "temperature", "precipitation", "soil_moisture", "sin_day", "cos_day"]
        self.cols = [c for c in base if c in feat.columns]
        return feat[self.cols].fillna(0).to_numpy(dtype=float)

    def fit(self, X, y):
        from sklearn.neural_network import MLPRegressor
        mask = pd.Series(np.asarray(y, dtype=float)).notna().to_numpy()
        M = self._mat(X.iloc[mask])
        self.model = MLPRegressor(hidden_layer_sizes=(128, 64), max_iter=800,
                                  random_state=self.seed)
        self.model.fit(M, np.asarray(y, dtype=float)[mask])
        return self

    def predict(self, feat):
        M = feat[self.cols].fillna(0).to_numpy(dtype=float) if self.cols else self._mat(feat)
        return np.clip(np.asarray(self.model.predict(M), dtype=float), 0.0, 1.0)


def make_fit_1d_heavy(known_df, clim_fit, seed):
    parts_X, parts_y, cols = [], [], []
    plan = ((1, 400, seed), (1, 200, seed + 21), (2, 120, seed + 1), (3, 80, seed + 2))
    for gap_len, n_gaps, s in plan:
        masked = mask_random_gaps(known_df, gap_len=gap_len, n_gaps=n_gaps, seed=s)
        if not masked["is_synthetic_gap"].any():
            continue
        feat, cols = build_features(masked, clim=clim_fit)
        Xp, yp = fit_rows_from_masked(masked, known_df, feat, cols)
        parts_X.append(Xp)
        parts_y.append(yp)
    return pd.concat(parts_X, ignore_index=True), pd.concat(parts_y, ignore_index=True), cols


class TmpAdapter:
    """Адаптер BigMLP под интерфейс predict_gaps (temporal.predict(feat))."""
    used_backend = "custom-mlp-128"

    def __init__(self, inner):
        self.inner = inner

    def predict(self, feat):
        return self.inner.predict(feat)


def main():
    df = normalize_columns(pd.read_csv(ROOT / "data" / "train_dataset.csv"))
    df = df[df[TARGET_COL].notna()].copy()
    train_df, valid_df = time_forward_splits(df)[-1]
    clim_train = PastClimatology().fit(train_df)
    X_fit, y_fit, cols = make_fit_1d_heavy(train_df, clim_train, SEED)
    print(f"1D-HEAVY fit_rows={len(X_fit)}", flush=True)
    gbm = BigGBM(seed=SEED).fit(X_fit, y_fit)
    tmp = TmpAdapter(BigMLP(seed=SEED).fit(X_fit, y_fit))
    base = {"gbm": gbm, "temporal": tmp, "feature_cols": cols}
    for gap_len in (1, 2, 3):
        y, pg, pt, ps, dso = collect(valid_df, clim_train, base, gap_len, [42, 43, 44, 45, 46])
        bg, wg = grid_best(y, pg, pt, ps, 0.05)
        print(f"gap {gap_len}d: gbm={rmse(y, pg):.4f} tmp={rmse(y, pt):.4f} "
              f"sea={rmse(y, ps):.4f} ENS={bg:.4f} (score {gap_score(bg)}) "
              f"w=({wg.w_gbm:.2f}/{wg.w_temporal:.2f}/{wg.w_seasonal:.2f})", flush=True)


if __name__ == "__main__":
    main()
