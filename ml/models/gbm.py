"""Модель A — Gradient Boosting (§9) с graceful fallback.

Порядок: CatBoost -> LightGBM -> sklearn HistGradientBoostingRegressor.
Первые два используются при наличии в окружении; в Docker/community-сборке
гарантированно работает sklearn-бэкенд без GPU и без сети. Интерфейс един:
fit(X, y) / predict(X) / used_backend.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


class GBMModel:
    used_backend: str = "none"

    def __init__(self, seed: int = 42):
        self.seed = seed
        self.model = None

    def fit(self, X: pd.DataFrame, y: pd.Series) -> "GBMModel":
        Xn = X.fillna(X.median(numeric_only=True)).fillna(0)
        # 1. CatBoost
        try:
            from catboost import CatBoostRegressor

            self.model = CatBoostRegressor(
                iterations=600, depth=6, learning_rate=0.05,
                loss_function="RMSE", random_seed=self.seed, verbose=False,
            )
            self.model.fit(Xn, y)
            self.used_backend = "catboost"
            return self
        except Exception:
            pass
        # 2. LightGBM
        try:
            from lightgbm import LGBMRegressor

            self.model = LGBMRegressor(
                n_estimators=600, max_depth=-1, num_leaves=63,
                learning_rate=0.05, subsample=0.9, colsample_bytree=0.8,
                random_state=self.seed, verbose=-1,
            )
            self.model.fit(Xn, y)
            self.used_backend = "lightgbm"
            return self
        except Exception:
            pass
        # 3. sklearn — всегда доступен
        from sklearn.ensemble import HistGradientBoostingRegressor

        self.model = HistGradientBoostingRegressor(
            max_iter=400, max_depth=8, learning_rate=0.06,
            l2_regularization=1.0, random_state=self.seed,
        )
        self.model.fit(Xn, y)
        self.used_backend = "sklearn-hgb"
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        Xn = X.fillna(0)
        pred = np.asarray(self.model.predict(Xn), dtype=float)
        return np.clip(pred, 0.0, 1.0)
