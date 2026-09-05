"""Модель A — Gradient Boosting (§9) с graceful fallback.

Порядок: CatBoost -> LightGBM -> sklearn HistGradientBoostingRegressor.
Первые два используются при наличии в окружении; в Docker/community-сборке
гарантированно работает sklearn-бэкенд без GPU и без сети. Интерфейс един:
fit(X, y) / predict(X) / used_backend.

Переменная VEGA_GBM_BACKEND=sklearn принудительно выбирает sklearn
(для абляций и воспроизводимости).
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd


class GBMModel:
    used_backend: str = "none"

    def __init__(self, seed: int = 42):
        self.seed = seed
        self.model = None

    def fit(self, X: pd.DataFrame, y: pd.Series) -> "GBMModel":
        mask = pd.Series(y).notna().to_numpy()
        X, y = X.iloc[mask].reset_index(drop=True) if hasattr(X, "iloc") else X, pd.Series(y).iloc[mask].reset_index(drop=True)
        Xn = X.fillna(X.median(numeric_only=True)).fillna(0)
        backend = os.getenv("VEGA_GBM_BACKEND", "").lower()
        force_sklearn = backend == "sklearn"
        skip_catboost = backend == "lightgbm"
        # 1. CatBoost
        if not force_sklearn and not skip_catboost:
            try:
                from catboost import CatBoostRegressor

                self.model = CatBoostRegressor(
                    iterations=3000, depth=6, learning_rate=0.01,
                    loss_function="RMSE", random_seed=self.seed, verbose=False,
                    early_stopping_rounds=200,
                    l2_leaf_reg=3,
                    border_count=255,
                )
                n = len(Xn)
                cut = max(int(n * 0.9), n - 5000)
                self.model.fit(Xn.iloc[:cut], y.iloc[:cut], eval_set=(Xn.iloc[cut:], y.iloc[cut:]))
                self.used_backend = "catboost"
                return self
            except Exception:
                pass
        # 2. LightGBM c time-ordered early stopping (последние 10% — свежие даты).
        if not force_sklearn:
            try:
                import lightgbm as lgb
                from lightgbm import LGBMRegressor

                self.model = LGBMRegressor(
                    n_estimators=6000, num_leaves=31,
                    learning_rate=0.01, subsample=0.8, colsample_bytree=0.7,
                    min_child_samples=200, reg_lambda=10.0,
                    random_state=self.seed, verbose=-1,
                )
                n = len(Xn)
                cut = max(int(n * 0.9), n - 5000)
                self.model.fit(
                    Xn.iloc[:cut], y.iloc[:cut],
                    eval_X=Xn.iloc[cut:], eval_y=y.iloc[cut:],
                    callbacks=[lgb.early_stopping(200, verbose=False)],
                )
                self.used_backend = "lightgbm"
                return self
            except Exception:
                pass
        # 3. sklearn — всегда доступен
        from sklearn.ensemble import HistGradientBoostingRegressor

        self.model = HistGradientBoostingRegressor(
            max_iter=1200, max_depth=8, learning_rate=0.03,
            l2_regularization=5.0, early_stopping="auto", random_state=self.seed,
        )
        self.model.fit(Xn, y)
        self.used_backend = "sklearn-hgb"
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        Xn = X.fillna(0)
        pred = np.asarray(self.model.predict(Xn), dtype=float)
        return np.clip(pred, 0.0, 1.0)
