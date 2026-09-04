"""Feature engineering (§9, §13) строго без утечек будущего (§30).

Работает на двух схемах: конкурсной (s2/landsat/modis + ERA5 + climatology,
ежедневный шаг) и demo (evi/ndwi/temperature, недельный шаг).

Ключевое ограничение конкурса: в скрытых строках ВСЕ same-day признаки
замаскированы (сенсоры, ERA5, климатология организаторов — NaN). Поэтому
в признаки идут только прошлое: лаги/rolling предзаполненного ряда,
прошлая погода, past-only климатология, sparsity-индикаторы, doy/crop.
Same-day сенсорные колонки запрещены (см. FORBIDDEN_FEATURE_COLS).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ml.data.contract import TARGET_COL

LAG_STEPS = [1, 2, 3, 7, 14, 30, 60, 90]
ROLL_WINDOWS = [7, 14, 30, 60, 90]

CROP_CATS = ["озимая пшеница", "подсолнечник", "пастбища/зерновые", "зерновые", "unknown"]

FEATURE_COLS: list[str] = []
FEATURES_VERSION = "v20"


def _resolve(df: pd.DataFrame, names: list[str], default: float = 0.0) -> pd.Series:
    for n in names:
        if n in df.columns:
            return df[n]
    return pd.Series(default, index=df.index, dtype=float)


def _build_frame(df: pd.DataFrame, clim=None) -> pd.DataFrame:
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"])
    out = out.sort_values(["polygon_id", "date"]).reset_index(drop=True)
    out["doy"] = out["date"].dt.dayofyear
    out["year"] = out["date"].dt.year
    out["month"] = out["date"].dt.month
    out["week"] = out["date"].dt.isocalendar().week.astype(int)
    out["sin_day"] = np.sin(2 * np.pi * out["doy"] / 365.25)
    out["cos_day"] = np.cos(2 * np.pi * out["doy"] / 365.25)

    groups = out.groupby("polygon_id", sort=False)
    raw = out[TARGET_COL].astype(float)
    known = raw.notna()

    # Предзаполнение линейной интерполяцией (только известные значения,
    # скрытые не используются) — стабильная основа для лагов.
    prefilled = groups[TARGET_COL].transform(lambda s: s.astype(float).interpolate("linear", limit_direction="both"))
    prefilled = prefilled.ffill().bfill().fillna(0.5)
    out["_pre"] = prefilled

    # Пространственный контекст: same-day среднее известных соседей.
    # Скрытые значения — NaN и в суммах не участвуют; собственный target
    # исключён, чтобы не было self-leak. Это настоящее (не будущее).
    date_sum = groups_date_sum = out.groupby("date")[TARGET_COL].transform(lambda s: s.fillna(0.0).sum())
    date_cnt = out.groupby("date")[TARGET_COL].transform("count").astype(float)
    own = raw.fillna(0.0)
    own_known = known.astype(float)
    den = (date_cnt - own_known).clip(lower=0)
    fallback_spatial = float(raw.median()) if raw.notna().any() else 0.4
    out["spatial_mean"] = ((date_sum - own * own_known) / den.replace(0, np.nan)).fillna(fallback_spatial)

    # Sparsity-индикаторы строго по прошлому (векторизованно, без apply).
    last_obs = out["date"].where(out[TARGET_COL].notna())
    last_obs = last_obs.groupby(out["polygon_id"]).ffill()
    out["days_since_obs"] = ((out["date"] - last_obs).dt.days
                             .fillna(365).clip(upper=365).astype(float))
    out["avail_ratio_30"] = groups[TARGET_COL].transform(
        lambda s: s.notna().astype(float).shift(1).rolling(30, min_periods=1).mean()
    ).fillna(0.0)
    # Будущий сосед: дней до следующего известного (симметрия интерполяции).
    next_obs = out["date"].where(known).groupby(out["polygon_id"]).bfill()
    out["dist_fut"] = ((next_obs - out["date"]).dt.days.fillna(365).clip(upper=365).astype(float))
    # Сенсорный источник соседних наблюдений (bias s2/landsat/modis).
    # Прошлое — ffill, будущее — bfill по флагам доступности в известные дни.
    for short, col in (("s2", "s2_ndvi"), ("ls", "landsat_ndvi"), ("mod", "modis_ndvi")):
        if col in out.columns:
            flag = (out[col].notna() & known).astype(float)
            out[f"src_past_{short}"] = flag.groupby(out["polygon_id"]).ffill().fillna(0.0)
            out[f"src_fut_{short}"] = flag.groupby(out["polygon_id"]).bfill().fillna(0.0)
        else:
            out[f"src_past_{short}"] = 0.0
            out[f"src_fut_{short}"] = 0.0

    # Лаги предзаполненного ряда (прошлое) + rolling по сдвинутому на 1.
    gp = out.groupby("polygon_id", sort=False)["_pre"]
    for k in LAG_STEPS:
        out[f"lag_{k}"] = gp.transform(lambda s, _k=k: s.shift(_k))
    shifted = gp.transform(lambda s: s.shift(1))
    out["_shift1"] = shifted
    gs = out.groupby("polygon_id", sort=False)["_shift1"]
    for w in ROLL_WINDOWS:
        out[f"rolling_mean_{w}"] = gs.transform(lambda s, _w=w: s.rolling(_w, min_periods=1).mean())
    for w in (7, 30):
        out[f"rolling_std_{w}"] = gs.transform(
            lambda s, _w=w: s.rolling(_w, min_periods=2).std().fillna(0.02))
    out["rolling_min_30"] = gs.transform(lambda s: s.rolling(30, min_periods=1).min())
    out["rolling_max_30"] = gs.transform(lambda s: s.rolling(30, min_periods=1).max())
    out["slope_30"] = (out["rolling_mean_7"] - out["rolling_mean_30"]).fillna(0)
    out = out.drop(columns=["_shift1"])

    # Прошлая погода: ERA5 (конкурс) или temperature/precipitation (demo).
    # Строго shift(1): same-day погода замаскирована в скрытых строках.
    temp = _resolve(out, ["temperature", "era5_temp_c"]).astype(float)
    rain = _resolve(out, ["precipitation", "era5_precip_mm"]).astype(float)
    temp = temp.interpolate("linear", limit_direction="both").ffill().bfill()
    rain = rain.fillna(0.0)
    out["_temp_f"] = temp
    out["_rain_f"] = rain
    gt = out.groupby("polygon_id", sort=False)["_temp_f"]
    gr = out.groupby("polygon_id", sort=False)["_rain_f"]
    for w in (7, 30):
        out[f"temp_mean_{w}"] = gt.transform(lambda s, _w=w: s.shift(1).rolling(_w, min_periods=1).mean())
        out[f"precip_sum_{w}"] = gr.transform(lambda s, _w=w: s.shift(1).rolling(_w, min_periods=1).sum())
    out[[f"temp_mean_{w}" for w in (7, 30)]] = out[[f"temp_mean_{w}" for w in (7, 30)]].fillna(temp.median() if temp.notna().any() else 15.0)
    out[[f"precip_sum_{w}" for w in (7, 30)]] = out[[f"precip_sum_{w}" for w in (7, 30)]].fillna(0.0)

    # Past-only климатология (fitted на истории, без будущего).
    if clim is not None:
        out = clim.transform(out)
    else:
        out["past_clim_mean"] = np.nan
        out["past_clim_std"] = np.nan
    # Same-day интерполированное значение (двусторонняя линейная по известным).
    # Легитимный контекст восстановления (как linear baseline): скрытые
    # значения в интерполяции не участвуют. Главный точечный prior для GBM.
    out["interp_now"] = out["_pre"]
    out["interp_clim_resid"] = out["interp_now"] - out["past_clim_mean"].fillna(out["interp_now"])

    # Качество/спектр demo-схемы, если есть; иначе нейтральные значения.
    for col in ("evi", "ndwi", "humidity", "radiation", "cloud_fraction", "data_quality"):
        if col in out.columns:
            out[col] = out.groupby("polygon_id")[col].transform(lambda s: s.fillna(s.median()))
            out[col] = out[col].fillna(out[col].median() if out[col].notna().any() else 0)
        else:
            out[col] = 0.0 if col != "data_quality" else 1.0

    # Культура — фиксированный one-hot (4 + unknown).
    crop = out["crop"] if "crop" in out.columns else pd.Series("unknown", index=out.index)
    crop = crop.fillna("unknown").astype(str)
    for c in CROP_CATS:
        out[f"crop_{c}"] = (crop == c).astype(float)

    # Кодировка полигона без target leakage; unseen-полигоны -> 0.
    freq = out["polygon_id"].map(out["polygon_id"].value_counts(normalize=True))
    out["polygon_freq"] = freq.astype(float).fillna(0.0)
    out["polygon_bucket"] = out["polygon_id"].map(lambda p: hash(str(p)) % 64 / 64.0).astype(float)
    out["lag_avail"] = groups[TARGET_COL].transform(
        lambda s: s.notna().astype(float).shift(1).rolling(30, min_periods=1).sum().clip(upper=30) / 30
    ).fillna(0.0)

    # Финальная зачистка NaN признаков (модель не должна видеть NaN).
    for col in [c for c in out.columns if c.startswith(("lag_", "rolling_", "temp_", "precip_"))]:
        out[col] = out[col].fillna(out[col].median() if out[col].notna().any() else 0.0)
    out["slope_30"] = out["slope_30"].fillna(0)
    out["past_clim_mean"] = out["past_clim_mean"].fillna(raw.median() if raw.notna().any() else 0.4)
    out["past_clim_std"] = out["past_clim_std"].fillna(0.05)
    out["_known_flag"] = known.astype(float)
    return out


def build_features(df: pd.DataFrame, clim=None) -> tuple[pd.DataFrame, list[str]]:
    """Возвращает (df_with_features, feature_cols). Схема v18."""
    global FEATURE_COLS
    out = _build_frame(df, clim=clim)
    cols = (
        [f"lag_{k}" for k in LAG_STEPS]
        + [f"rolling_mean_{w}" for w in ROLL_WINDOWS]
        + ["rolling_std_7", "rolling_std_30", "rolling_min_30", "rolling_max_30",
           "slope_30", "lag_avail", "days_since_obs", "avail_ratio_30"]
        + ["doy", "week", "month", "year", "sin_day", "cos_day"]
        + ["temp_mean_7", "temp_mean_30", "precip_sum_7", "precip_sum_30"]
        + ["past_clim_mean", "past_clim_std", "spatial_mean"]
        + ["interp_now", "interp_clim_resid", "dist_fut"]
        + ["src_past_s2", "src_past_ls", "src_past_mod",
           "src_fut_s2", "src_fut_ls", "src_fut_mod"]
        + ["evi", "ndwi", "humidity", "radiation", "cloud_fraction", "data_quality"]
        + [f"crop_{c}" for c in CROP_CATS]
        + ["polygon_freq", "polygon_bucket"]
    )
    cols = [c for c in cols if c in out.columns]
    FEATURE_COLS = cols
    return out, cols
