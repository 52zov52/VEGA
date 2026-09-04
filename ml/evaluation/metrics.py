"""Метрики конкурсной задачи A (§1): RMSE и GapScore."""
from __future__ import annotations

import numpy as np


def rmse(y_true, y_pred) -> float:
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    mask = np.isfinite(y_true) & np.isfinite(y_pred)
    if not mask.any():
        return float("nan")
    return float(np.sqrt(np.mean((y_true[mask] - y_pred[mask]) ** 2)))


def gap_score(r: float) -> float:
    """GapScore = round(30 * max(0, 1 - RMSE/0.10), 2)."""
    return round(30 * max(0.0, 1 - r / 0.10), 2)
