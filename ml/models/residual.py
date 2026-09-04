"""Residual-обёртка над GBM: модель учит поправку к линейному prior (§9).

Без неё дерево с признаком interp_now вырождается в тождество
pred = interp_now (проверено: RMSE в точности равен linear). Здесь
target для бустинга — остаток y - interp_now, итог — prior + поправка.
Обёртка picklable и сохраняется в артефакты как обычная модель.
"""
from __future__ import annotations

import pandas as pd

from ml.models.gbm import GBMModel

PRIOR_COL = "interp_now"


class ResidualGBM:
    used_backend: str = "none"

    def __init__(self, seed: int = 42, prior_col: str = PRIOR_COL):
        self.seed = seed
        self.prior_col = prior_col
        self.inner = GBMModel(seed=seed)
        self.model_cols: list[str] = []

    def fit(self, X: pd.DataFrame, y: pd.Series) -> "ResidualGBM":
        self.model_cols = [c for c in X.columns if c != self.prior_col]
        prior = X[self.prior_col].astype(float) if self.prior_col in X.columns else 0.0
        resid = pd.Series(y, index=X.index).astype(float) - pd.Series(prior, index=X.index).astype(float)
        self.inner.fit(X[self.model_cols], resid)
        self.used_backend = f"residual({self.inner.used_backend})"
        return self

    def predict(self, X: pd.DataFrame) -> pd.DataFrame:
        import numpy as np

        cols = [c for c in self.model_cols if c in X.columns]
        prior = X[self.prior_col].astype(float).to_numpy() if self.prior_col in X.columns else np.zeros(len(X))
        corr = np.asarray(self.inner.predict(X[cols] if cols else X), dtype=float)
        return np.clip(prior + corr, 0.0, 1.0)
