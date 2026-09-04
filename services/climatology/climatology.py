"""Климатологическая норма NDVI_climatology(doy) (§14).

Ожидаемое значение NDVI для конкретной фазы сезона по истории полигона:
mean/std по дню года в окне ±7 дней со сглаживанием. Anomaly и Z считаются
от этой нормы; это же база seasonal baseline и Z-score детектора.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ml.data.contract import TARGET_COL


def build_climatology(df: pd.DataFrame, window: int = 7) -> pd.DataFrame:
    work = df.copy()
    work["_d"] = pd.to_datetime(work["date"])
    work["_doy"] = work["_d"].dt.dayofyear
    rows: list[dict] = []
    for (pid, doy), _ in work.groupby(["polygon_id", "_doy"]):
        vals: list[float] = []
        for d in range(int(doy) - window, int(doy) + window + 1):
            dd = ((d - 1) % 366) + 1
            vals += work[(work["polygon_id"] == pid) & (work["_doy"] == dd)][TARGET_COL].dropna().tolist()
        if vals:
            rows.append({"polygon_id": pid, "doy": int(doy),
                         "clim_mean": float(np.mean(vals)),
                         "clim_std": float(max(np.std(vals), 0.02)),
                         "clim_n": int(len(vals))})
    clim = pd.DataFrame(rows)
    if len(clim):
        # лёгкое сглаживание по дню года внутри полигона
        clim = clim.sort_values(["polygon_id", "doy"])
        clim["clim_mean"] = clim.groupby("polygon_id")["clim_mean"].transform(
            lambda s: s.rolling(15, center=True, min_periods=1).mean())
    return clim


def attach_climatology(df: pd.DataFrame, clim: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()
    work["_d"] = pd.to_datetime(work["date"])
    work["_doy"] = work["_d"].dt.dayofyear
    out = work.merge(clim, left_on=["polygon_id", "_doy"], right_on=["polygon_id", "doy"], how="left")
    global_mean = float(work[TARGET_COL].median()) if TARGET_COL in work and work[TARGET_COL].notna().any() else 0.5
    out["clim_mean"] = out["clim_mean"].fillna(global_mean)
    out["clim_std"] = out["clim_std"].fillna(0.05)
    out["zscore"] = (out[TARGET_COL] - out["clim_mean"]) / out["clim_std"].clip(lower=0.02)
    return out.drop(columns=[c for c in ("_d", "_doy", "doy", "clim_n") if c in out.columns])
