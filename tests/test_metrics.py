"""Тесты метрик и бейзлайнов (быстрые, без тяжёлых зависимостей)."""
import numpy as np
import pandas as pd

from ml.data.contract import TARGET_COL
from ml.evaluation.metrics import gap_score, rmse
from ml.models.baselines import baseline_linear, baseline_nearest


def test_gap_score_scale():
    assert gap_score(0.0) == 30
    assert gap_score(0.02) == 24
    assert gap_score(0.05) == 15
    assert gap_score(0.10) == 0
    assert gap_score(0.5) == 0


def test_rmse_perfect():
    assert rmse(np.array([0.5, 0.6]), np.array([0.5, 0.6])) == 0.0


def test_baselines_fill_gaps():
    s = pd.Series([0.5, np.nan, np.nan, 0.8])
    assert baseline_nearest(s).isna().sum() == 0
    assert baseline_linear(s).isna().sum() == 0
    # линейность середины
    assert abs(baseline_linear(s).iloc[1] - 0.6) < 1e-9
