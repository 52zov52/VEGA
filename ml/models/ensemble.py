"""Финальный ансамбль (§9): w1*GBM + w2*Temporal + w3*Seasonal.

Веса подбираются на validation перебором по сетке (см. scripts/train.py),
по умолчанию — из .env (0.55 / 0.30 / 0.15). Клиппинг в [0, 1].
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class EnsembleWeights:
    w_gbm: float = 0.55
    w_temporal: float = 0.30
    w_seasonal: float = 0.15

    def normalized(self) -> "EnsembleWeights":
        s = self.w_gbm + self.w_temporal + self.w_seasonal
        if s <= 0:
            return EnsembleWeights(0.55, 0.30, 0.15)
        return EnsembleWeights(self.w_gbm / s, self.w_temporal / s, self.w_seasonal / s)


def ensemble_predict(
    p_gbm: np.ndarray,
    p_temporal: np.ndarray,
    p_seasonal: np.ndarray,
    weights: EnsembleWeights | None = None,
) -> np.ndarray:
    w = (weights or EnsembleWeights()).normalized()
    gbm = np.asarray(p_gbm, dtype=float)
    tmp = np.asarray(p_temporal, dtype=float)
    sea = np.asarray(p_seasonal, dtype=float)
    # Устойчивость к NaN компонентов: 0 * NaN = NaN, поэтому веса
    # перераспределяются на доступные компоненты (важно для полностью
    # скрытых рядов, где seasonal не может построиться).
    ws = np.array([w.w_gbm, w.w_temporal, w.w_seasonal], dtype=float)
    stack = np.vstack([gbm, tmp, sea])
    valid = np.isfinite(stack)
    wsum = (valid * ws[:, None]).sum(axis=0)
    out = (np.where(valid, stack, 0.0) * ws[:, None]).sum(axis=0)
    out = np.divide(out, wsum, out=np.full_like(out, 0.5), where=wsum > 0)
    return np.clip(out, 0.0, 1.0)


def grid_search_weights(
    y_true: np.ndarray,
    p_gbm: np.ndarray,
    p_temporal: np.ndarray,
    p_seasonal: np.ndarray,
) -> EnsembleWeights:
    """Полный перебор весов с шагом 0.05 по RMSE на validation."""
    from ml.evaluation.metrics import rmse

    best: EnsembleWeights = EnsembleWeights()
    best_score = float("inf")
    steps = [i / 20 for i in range(21)]
    for a in steps:
        for b in steps:
            c = 1.0 - a - b
            if c < -1e-9 or c > 1:
                continue
            score = rmse(y_true, ensemble_predict(p_gbm, p_temporal, p_seasonal, EnsembleWeights(a, b, max(c, 0))))
            if score < best_score:
                best_score = score
                best = EnsembleWeights(a, b, max(c, 0))
    return best.normalized()


# Стратификация весов по давности последнего наблюдения (days_since_obs):
# свежим точкам важнее GBM/interp, далёким — seasonal. Границы из ablation.
DSO_BINS: tuple[tuple[str, int, int | None], ...] = (
    ("dso1-2", 0, 2),
    ("dso3-7", 3, 7),
    ("dso8+", 8, None),
)


def dso_bin_names(dso: np.ndarray) -> np.ndarray:
    dso = np.asarray(dso, dtype=float)
    out = np.full(dso.shape, "dso8+", dtype=object)
    out[dso <= 2] = "dso1-2"
    out[(dso >= 3) & (dso <= 7)] = "dso3-7"
    return out


def apply_stratified(
    p_gbm: np.ndarray,
    p_temporal: np.ndarray,
    p_seasonal: np.ndarray,
    dso: np.ndarray | None,
    weights_by_bin: dict[str, EnsembleWeights] | None,
    fallback: EnsembleWeights | None = None,
) -> np.ndarray:
    """Взвешивание по бинам dso; без dso/весов — обычный глобальный ансамбль."""
    if not weights_by_bin or dso is None:
        return ensemble_predict(p_gbm, p_temporal, p_seasonal, fallback)
    names = dso_bin_names(dso)
    out = np.zeros_like(np.asarray(p_gbm, dtype=float))
    for name, _, _ in DSO_BINS:
        m = names == name
        if not m.any():
            continue
        w = weights_by_bin.get(name) or fallback
        out[m] = ensemble_predict(
            np.asarray(p_gbm, dtype=float)[m],
            np.asarray(p_temporal, dtype=float)[m],
            np.asarray(p_seasonal, dtype=float)[m],
            w,
        )
    return out
