"""Time-aware validation (§10): forward splits + leave-polygon-out.

Обычный random split запрещён — он даёт leakage внутри одного временного
ряда и завышает качество. Здесь только сплиты по времени и по полигонам.
"""
from __future__ import annotations

import pandas as pd


def time_forward_splits(df: pd.DataFrame, date_col: str = "date") -> list[tuple[pd.DataFrame, pd.DataFrame]]:
    """Два фолда: train 2019-2022/valid 2023 и train 2019-2023/valid 2024."""
    work = df.copy()
    work["_y"] = pd.to_datetime(work[date_col]).dt.year
    splits = []
    for train_years, valid_year in (([2019, 2020, 2021, 2022], 2023), ([2019, 2020, 2021, 2022, 2023], 2024)):
        tr = work[work["_y"].isin(train_years)].drop(columns=["_y"])
        va = work[work["_y"] == valid_year].drop(columns=["_y"])
        if len(tr) and len(va):
            splits.append((tr.reset_index(drop=True), va.reset_index(drop=True)))
    # Fallback для коротких demo-диапазонов: сплит по медиане даты.
    if not splits and len(work):
        cut = pd.to_datetime(work[date_col]).median()
        tr = work[pd.to_datetime(work[date_col]) < cut].drop(columns=["_y"])
        va = work[pd.to_datetime(work[date_col]) >= cut].drop(columns=["_y"])
        splits.append((tr.reset_index(drop=True), va.reset_index(drop=True)))
    return splits


def leave_polygon_out(df: pd.DataFrame, polygon_col: str = "polygon_id"):
    """Генератор (train, valid, held_polygon) — проверка переноса между регионами."""
    for pid in sorted(df[polygon_col].astype(str).unique()):
        tr = df[df[polygon_col] != pid].reset_index(drop=True)
        va = df[df[polygon_col] == pid].reset_index(drop=True)
        if len(tr) and len(va):
            yield tr, va, pid
