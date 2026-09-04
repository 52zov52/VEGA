"""Multi-signal детектор аномалий (§15-16) поверх Z-score (§14).

Веса конфигурируются через .env. Пороговые уровни:
Z > -1 normal, -2..-1 watch/stress, < -2 critical (с учётом длительности и тренда).
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd

from ml.data.contract import TARGET_COL


def _w(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def detect_anomalies(df: pd.DataFrame, clim: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    from services.climatology.climatology import attach_climatology

    w_ndvi = _w("ANOMALY_W_NDVI", 0.35)
    w_evi = _w("ANOMALY_W_EVI", 0.15)
    w_ndwi = _w("ANOMALY_W_NDWI", 0.15)
    w_wx = _w("ANOMALY_W_WEATHER", 0.15)
    w_soil = _w("ANOMALY_W_SOIL", 0.10)
    w_trend = _w("ANOMALY_W_TREND", 0.10)

    work = attach_climatology(df, clim).sort_values(["polygon_id", "date"]).copy()
    # нормированные сигналы 0..1 (сила негативного отклонения)
    work["sig_ndvi"] = (-work["zscore"]).clip(lower=0, upper=4) / 4
    for col, sig in (("evi", "sig_evi"), ("ndwi", "sig_ndwi")):
        if col in work.columns:
            m = work.groupby("polygon_id")[col].transform("mean")
            s = work.groupby("polygon_id")[col].transform("std").fillna(0.05).clip(lower=0.02)
            work[sig] = ((m - work[col]) / s).clip(lower=0, upper=4) / 4
        else:
            work[sig] = 0.0
    # погодный стресс: жара + дефицит осадков относительно среднего полигона
    if "temperature" in work.columns:
        tm = work.groupby("polygon_id")["temperature"].transform("mean")
        work["sig_heat"] = ((work["temperature"] - tm) / 5.0).clip(lower=0, upper=3) / 3
    else:
        work["sig_heat"] = 0.0
    if "precipitation" in work.columns:
        # скользящая сумма осадков 30 дней vs средняя
        pr = work.groupby("polygon_id")["precipitation"].transform(lambda s: s.fillna(0).rolling(4, min_periods=1).sum())
        prm = pr.mean()
        work["sig_dry"] = ((prm - pr) / max(prm, 1.0)).clip(lower=0, upper=1)
    else:
        work["sig_dry"] = 0.0
    work["sig_weather"] = (work["sig_heat"] + work["sig_dry"]) / 2
    if "soil_moisture" in work.columns:
        sm = work.groupby("polygon_id")["soil_moisture"].transform("mean")
        work["sig_soil"] = ((sm - work["soil_moisture"]) / 0.15).clip(lower=0, upper=2) / 2
    else:
        work["sig_soil"] = 0.0
    # тренд: скорость падения NDVI за 2 шага
    work["ndvi_slope"] = work.groupby("polygon_id")[TARGET_COL].transform(lambda s: s.diff(2) / 2)
    work["sig_trend"] = ((-work["ndvi_slope"]) / 0.05).clip(lower=0, upper=2) / 2

    work["anomaly_score"] = (
        w_ndvi * work["sig_ndvi"] + w_evi * work["sig_evi"] + w_ndwi * work["sig_ndwi"]
        + w_wx * work["sig_weather"] + w_soil * work["sig_soil"] + w_trend * work["sig_trend"]
    ).clip(0, 1)

    def level(row) -> str:
        # комбинируем z и score, чтобы не срабатывать на одиночный шумовой пик
        if row["zscore"] < -2 and row["anomaly_score"] > 0.55:
            return "critical"
        if row["zscore"] < -1.5 and row["anomaly_score"] > 0.4:
            return "stress"
        if row["zscore"] < -1 and row["anomaly_score"] > 0.3:
            return "watch"
        return "normal"

    work["level"] = work.apply(level, axis=1)
    work["deviation_pct"] = ((work[TARGET_COL] - work["clim_mean"]) / work["clim_mean"].clip(lower=0.05) * 100).fillna(0)

    # группируем последовательные stress/critical в события
    events: list[dict] = []
    for pid, sub in work.sort_values("date").groupby("polygon_id"):
        sub = sub.reset_index(drop=True)
        start = None
        for i, r in sub.iterrows():
            bad = r["level"] in ("stress", "critical")
            if bad and start is None:
                start = i
            if (not bad or i == len(sub) - 1) and start is not None:
                end = i if not bad else i
                seg = sub.iloc[start:end if not bad else end + 1]
                if len(seg) == 0:
                    start = None
                    continue
                worst = seg.loc[seg["anomaly_score"].idxmax()]
                events.append({
                    "polygon_id": pid,
                    "start_date": str(seg["date"].iloc[0]),
                    "end_date": str(seg["date"].iloc[-1]),
                    "level": "critical" if (seg["level"] == "critical").any() else "stress",
                    "anomaly_score": round(float(worst["anomaly_score"]), 3),
                    "zscore": round(float(worst["zscore"]), 2),
                    "deviation_pct": round(float(worst["deviation_pct"]), 1),
                    "duration_steps": int(len(seg)),
                    "data_quality": round(float(seg["data_quality"].mean()) if "data_quality" in seg else 1.0, 3),
                })
                start = None
    # соседнее отклонение: флаг локальной проблемы (§18 сценарий 2)
    if events:
        mean_dev = work.groupby("date")["deviation_pct"].mean().to_dict()
        for e in events:
            e["neighbour_deviation"] = round(float(mean_dev.get(pd.to_datetime(e["start_date"]).date(), 0)), 1)
    return work, events
