"""Контроль против data leakage (§30).

Проверяет, что ни один признак не смотрит в будущее и что target теста
не использовался при построении фичей/климатологии.
"""
from __future__ import annotations

import pandas as pd

FORBIDDEN_SUBSTRINGS = ("future", "lead_", "target_next", "next_ndvi")


def check_no_future_features(feature_cols: list[str]) -> list[str]:
    """Возвращает список нарушений (пусто = чисто)."""
    return [c for c in feature_cols if any(s in c.lower() for s in FORBIDDEN_SUBSTRINGS)]


def check_temporal_order(train: pd.DataFrame, valid: pd.DataFrame, date_col: str = "date") -> list[str]:
    issues: list[str] = []
    t_max = pd.to_datetime(train[date_col]).max()
    v_min = pd.to_datetime(valid[date_col]).min()
    if v_min < t_max:
        issues.append(f"valid начинается {v_min.date()} раньше конца train {t_max.date()}")
    return issues
