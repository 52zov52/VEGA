"""Предобработка временного ряда (§6): фильтрация облаков, агрегация, нормализация дат."""
from __future__ import annotations

import pandas as pd

from ml.data.contract import TARGET_COL


def preprocess_observations(df: pd.DataFrame, cloud_thr: float = 0.6) -> pd.DataFrame:
    """Cloud/quality filtering + spatial aggregation + date normalization + gap detection."""
    out = df.copy()
    # нормализуем имена
    out.columns = [c.strip().lower() for c in out.columns]
    if "polygon_id" not in out.columns:
        for cand in ("anon_polygon_id", "field_id"):
            if cand in out.columns:
                out = out.rename(columns={cand: "polygon_id"})
                break
    out["date"] = pd.to_datetime(out["date"]).dt.date
    # фильтрация облачности: помечаем пропуском, а не удаляем строку (важно для RMSE-разметки)
    if "cloud_fraction" in out.columns:
        cloudy = out["cloud_fraction"].fillna(0) > cloud_thr
        out.loc[cloudy, TARGET_COL] = pd.NA
        out.loc[cloudy, "data_quality"] = out.loc[cloudy, "data_quality"].fillna(0.2) * 0.5
    # пространственная агрегация: медиана по полигону и дате
    num_cols = out.select_dtypes("number").columns.tolist()
    agg = {c: "median" for c in num_cols if c not in ("latitude", "longitude")}
    if agg:
        out = out.groupby(["polygon_id", "date"], as_index=False).agg(
            {**agg, **({} if "provider" in out.columns else {})})
    out = out.sort_values(["polygon_id", "date"]).reset_index(drop=True)
    out["is_gap"] = out[TARGET_COL].isna()
    return out
