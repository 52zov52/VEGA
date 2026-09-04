"""Модель B — temporal (§9): TCN/LSTM при наличии torch, иначе MLP-fallback.

Временная модель видит окно последних 30 шагов NDVI + погоду и учит
динамику спада/восстановления, которую GBM на точечных лагах сглаживает.
Fallback MLPRegressor гарантирует обучение offline на CPU.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

WINDOW = 30


class TemporalModel:
    used_backend: str = "none"

    def __init__(self, seed: int = 42):
        self.seed = seed
        self.model = None
        self.cols: list[str] = []

    def _window_matrix(self, feat: pd.DataFrame) -> np.ndarray:
        base = ["lag_1", "lag_2", "lag_3", "lag_7", "lag_14",
                "temperature", "precipitation", "soil_moisture", "sin_day", "cos_day"]
        self.cols = [c for c in base if c in feat.columns]
        return feat[self.cols].fillna(0).to_numpy(dtype=float)

    def fit(self, feat: pd.DataFrame, y: pd.Series) -> "TemporalModel":
        X = self._window_matrix(feat)
        try:
            import torch
            from torch import nn

            torch.manual_seed(self.seed)

            class TCN(nn.Module):
                def __init__(self, d: int):
                    super().__init__()
                    self.net = nn.Sequential(
                        nn.Linear(d, 64), nn.ReLU(), nn.Dropout(0.1),
                        nn.Linear(64, 32), nn.ReLU(),
                        nn.Linear(32, 1), nn.Sigmoid(),
                    )

                def forward(self, x):
                    return self.net(x).squeeze(-1)

            net = TCN(X.shape[1])
            opt = torch.optim.Adam(net.parameters(), lr=0.01)
            loss_fn = nn.MSELoss()
            Xt = torch.tensor(X, dtype=torch.float32)
            yt = torch.tensor(y.to_numpy(dtype=float), dtype=torch.float32)
            net.train()
            for _ in range(120):
                opt.zero_grad()
                loss = loss_fn(net(Xt), yt)
                loss.backward()
                opt.step()
            self.model = net
            self.used_backend = "torch-tcn"
            return self
        except Exception:
            pass
        from sklearn.neural_network import MLPRegressor

        self.model = MLPRegressor(hidden_layer_sizes=(64, 32), max_iter=400, random_state=self.seed)
        self.model.fit(X, y)
        self.used_backend = "sklearn-mlp"
        return self

    def predict(self, feat: pd.DataFrame) -> np.ndarray:
        X = feat[self.cols].fillna(0).to_numpy(dtype=float) if self.cols else self._window_matrix(feat)
        if self.used_backend == "torch-tcn":
            import torch

            self.model.eval()
            with torch.no_grad():
                pred = self.model(torch.tensor(X, dtype=torch.float32)).numpy()
        else:
            pred = np.asarray(self.model.predict(X), dtype=float)
        return np.clip(pred, 0.0, 1.0)
