"""Feature engineering (§9, §13) строго без утечек будущего (§30).

Все lag/rolling признаки считаются только по прошлым значениям внутри
каждого полигона (shift + rolling по сдвинутому ряду). Признаки погоды и
спектральных индексов берутся на текущую дату — они доступны из провайдеров
на момент прогноза. Будущие значения primary_ndvi запрещены — это проверяет
ml.evaluation.leakage.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ml.data.contract import TARGET_COL

LAG_STEPS = [1, 2, 3, 7, 14, 30]
ROLL_WINDOWS = [3, 7, 14, 30]

# Финальный список фичей фиксирован — та же схема используется в train и inference.
FEATURE_COLS: list[str] = []


def _build_frame(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"])
    out = out.sort_values(["polygon_id", "date"]).reset_index(drop=True)
    out["doy"] = out["date"].dt.dayofyear
    out["week"] = out["date"].dt.isocalendar().week.astype(int)
    out["month"] = out["date"].dt.month
    out["year"] = out["date"].dt.year
    out["sin_day"] = np.sin(2 * np.pi * out["doy"] / 365.25)
    out["cos_day"] = np.cos(2 * np.pi * out["doy"] / 365.25)

    g = out.groupby("polygon_id", sort=False)[TARGET_COL]
    # Лаги только в прошлое: shift(k) гарантирует отсутствие leakage.
    for k in LAG_STEPS:
        out[f"lag_{k}"] = g.transform(lambda s, _k=k: s.shift(_k))
    # Rolling только по сдвинутому на 1 ряду — иначе в окно попадёт текущий target.
    shifted = g.transform(lambda s: s.shift(1))
    out["_shift1"] = shifted
    gs = out.groupby("polygon_id", sort=False)["_shift1"]
    for w in ROLL_WINDOWS:
        out[f"rolling_mean_{w}"] = gs.transform(lambda s, _w=w: s.rolling(_w, min_periods=1).mean())
        if w in (7, 14, 30):
            out[f"rolling_std_{w}"] = gs.transform(
                lambda s, _w=w: s.rolling(_w, min_periods=2).std().fillna(0.02)
            )
    out["rolling_min_14"] = gs.transform(lambda s: s.rolling(14, min_periods=1).min())
    out["rolling_max_14"] = gs.transform(lambda s: s.rolling(14, min_periods=1).max())
    out["slope_7"] = (out["rolling_mean_3"] - out["rolling_mean_14"]).fillna(0)
    # Доступность лагов — модель должна знать, что ряд начался недавно.
    out["lag_avail"] = g.transform(lambda s: s.shift(1).notna().cumsum().clip(upper=30) / 30)
    # Кодировка полигона без target leakage: частотный + хеш-бакет.
    freq = out["polygon_id"].map(out["polygon_id"].value_counts(normalize=True))
    out["polygon_freq"] = freq.astype(float)
    out["polygon_bucket"] = out["polygon_id"].map(lambda p: hash(str(p)) % 64 / 64.0).astype(float)
    out = out.drop(columns=["_shift1"])
    # Пропуски в погоде/качестве — медиана по полигону, затем глобальная.
    for col in ("evi", "ndwi", "temperature", "precipitation", "soil_moisture",
                "radiation", "humidity", "cloud_fraction", "data_quality"):
        if col in out.columns:
            out[col] = out.groupby("polygon_id")[col].transform(lambda s: s.fillna(s.median()))
            out[col] = out[col].fillna(out[col].median() if out[col].notna().any() else 0)
        else:
            out[col] = 0.0
    # Лаги без истории заполняем сезонной оценкой, а не будущим.
    for col in [c for c in out.columns if c.startswith(("lag_", "rolling_"))]:
        out[col] = out[col].fillna(out.groupby("doy")[TARGET_COL].transform("mean"))
        out[col] = out[col].fillna(out[TARGET_COL].median() if out[TARGET_COL].notna().any() else 0.5)
    out["slope_7"] = out["slope_7"].fillna(0)
    return out


def build_features(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Возвращает (df_with_features, feature_cols). Детерминировано по схеме v17."""
    global FEATURE_COLS
    out = _build_frame(df)
    cols = (
        [f"lag_{k}" for k in LAG_STEPS]
        + [f"rolling_mean_{w}" for w in ROLL_WINDOWS]
        + ["rolling_std_7", "rolling_std_14", "rolling_std_30",
           "rolling_min_14", "rolling_max_14", "slope_7", "lag_avail"]
        + ["doy", "week", "month", "year", "sin_day", "cos_day"]
        + ["evi", "ndwi", "temperature", "precipitation", "soil_moisture",
           "radiation", "humidity", "cloud_fraction", "data_quality",
           "polygon_freq", "polygon_bucket"]
    )
    cols = [c for c in cols if c in out.columns]
    FEATURE_COLS = cols
    return out, cols


FEATURES_VERSION = "v17"
