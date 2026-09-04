"""4 baseline (§8): nearest, linear, seasonal + наивный средний.

Seasonal baseline — медиана того же полигона в окне ±14 дней day-of-year
по прошлым годам (без будущего). Все функции работают на Series с NaN
в местах пропусков и возвращают заполненный Series.
"""
from __future__ import annotations

import pandas as pd


def baseline_nearest(s: pd.Series) -> pd.Series:
    """Forward/backward nearest valid value."""
    return s.ffill().bfill()


def baseline_linear(s: pd.Series) -> pd.Series:
    """Линейная интерполяция + концевые nearest (pandas, limit_direction=both)."""
    out = s.astype(float).interpolate(method="linear", limit_direction="both")
    return out.ffill().bfill()


def baseline_seasonal(df: pd.DataFrame, target: str = "primary_ndvi") -> pd.Series:
    """Сезонная медиана по doy-окну прошлых лет внутри полигона.

    Для каждой строки берём медиану известных значений того же полигона,
    чей day-of-year в пределах ±14 дней. Если истории нет — линейный fallback.
    """
    work = df.copy()
    work["_d"] = pd.to_datetime(work["date"])
    work["_doy"] = work["_d"].dt.dayofyear
    filled = work[target].copy()
    for pid, idx in work.groupby("polygon_id").groups.items():
        sub = work.loc[idx]
        known = sub[sub[target].notna()]
        if not known.empty:
            for i in idx[sub[target].isna()]:
                doy = work.at[i, "_doy"]
                # циркулярная дистанция по дню года
                dist = (known["_doy"] - doy).abs()
                dist = dist.clip(upper=366 - dist.clip(upper=183))
                window = known.loc[dist <= 14, target]
                if len(window):
                    filled.at[i] = float(window.median())
    return baseline_linear(filled)


def baseline_mean(s: pd.Series) -> pd.Series:
    m = float(s.mean()) if s.notna().any() else 0.5
    return s.fillna(m)
