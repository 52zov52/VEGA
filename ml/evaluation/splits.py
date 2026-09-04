"""Time-aware validation (§10): forward splits + leave-polygon-out.

Обычный random split запрещён — он даёт leakage внутри одного временного
ряда и завышает качество. Только сплиты по времени и по полигонам.
Годы определяются по данным: последние два года — validation-фолды.
"""
from __future__ import annotations

import pandas as pd


def time_forward_splits(df: pd.DataFrame, date_col: str = "date") -> list[tuple[pd.DataFrame, pd.DataFrame]]:
    """Два фолда: train до Y-2/valid Y-1 и train до Y-1/valid Y (Y — последний год)."""
    work = df.copy()
    work["_y"] = pd.to_datetime(work[date_col]).dt.year
    years = sorted(work["_y"].dropna().unique().tolist())
    splits: list[tuple[pd.DataFrame, pd.DataFrame]] = []
    if len(years) >= 2:
        for vy in years[-2:]:
            tr = work[work["_y"] < vy].drop(columns=["_y"])
            va = work[work["_y"] == vy].drop(columns=["_y"])
            if len(tr) and len(va):
                splits.append((tr.reset_index(drop=True), va.reset_index(drop=True)))
    if not splits and len(work):
        # Короткий диапазон: сплит по медиане даты.
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
