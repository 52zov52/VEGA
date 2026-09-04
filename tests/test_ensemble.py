"""Регрессия: ансамбль устойчив к NaN компонентов (полностью скрытый ряд)."""
import numpy as np

from ml.models.ensemble import EnsembleWeights, ensemble_predict


def test_ensemble_ignores_nan_components():
    gbm = np.array([0.6, 0.7])
    nan = np.array([float("nan"), float("nan")])
    out = ensemble_predict(gbm, nan, nan, EnsembleWeights(0.55, 0.30, 0.15))
    assert np.allclose(out, gbm), "веса должны перераспределиться на доступный компонент"


def test_ensemble_all_nan_falls_back():
    nan = np.array([float("nan")])
    out = ensemble_predict(nan, nan, nan, EnsembleWeights(0.55, 0.30, 0.15))
    assert np.isfinite(out).all()
