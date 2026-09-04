"""Интерпретация причин аномалии (§17-18, §24).

LLM используется только поверх структурированных сигналов: этот модуль формирует
детерминированное заключение + текст, а опциональный LLM-слой лишь перефразирует его.
"""
from __future__ import annotations

import pandas as pd


def explain_event(event: dict, ts: pd.DataFrame, weather_available: bool = True) -> dict:
    """Строит карточку WHY IS THIS ANOMALY по сегменту временного ряда."""
    seg = ts[(ts["polygon_id"] == event["polygon_id"]) &
             (pd.to_datetime(ts["date"]) >= pd.to_datetime(event["start_date"])) &
             (pd.to_datetime(ts["date"]) <= pd.to_datetime(event["end_date"]))]
    clim_mean = float(seg["clim_mean"].mean()) if "clim_mean" in seg and len(seg) else float("nan")
    actual = float(seg["primary_ndvi"].mean()) if "primary_ndvi" in seg and len(seg) else float("nan")
    dev = event.get("deviation_pct", 0)

    factors: list[dict] = []

    def add(name: str, delta: float, strength: str, direction: str):
        factors.append({"signal": name, "delta_pct": round(float(delta), 1),
                        "strength": strength, "direction": direction})

    # осадки и почва — главные сигналы гидрологического стресса
    if "precipitation" in seg and seg["precipitation"].notna().any() and weather_available:
        rain = float(seg["precipitation"].fillna(0).sum())
        base = float(ts[ts["polygon_id"] == event["polygon_id"]]["precipitation"].fillna(0).mean() * max(len(seg), 1))
        rain_dev = (rain - base) / max(base, 0.5) * 100
        add("precipitation", rain_dev, "сильный" if rain_dev < -30 else ("умеренный" if rain_dev < -10 else "слабый"),
            "down" if rain_dev < 0 else "up")
    if "soil_moisture" in seg and seg["soil_moisture"].notna().any():
        sm = float(seg["soil_moisture"].mean())
        sm_base = float(ts[ts["polygon_id"] == event["polygon_id"]]["soil_moisture"].mean())
        sm_dev = (sm - sm_base) / max(sm_base, 0.05) * 100
        add("soil_moisture", sm_dev, "сильный" if sm_dev < -20 else ("умеренный" if sm_dev < -8 else "слабый"),
            "down" if sm_dev < 0 else "up")
    if "temperature" in seg and seg["temperature"].notna().any() and weather_available:
        t = float(seg["temperature"].mean())
        tb = float(ts[ts["polygon_id"] == event["polygon_id"]]["temperature"].mean())
        add("temperature_c", t - tb, "умеренный" if abs(t - tb) > 2 else "слабый", "up" if t > tb else "down")
    if "ndwi" in seg and seg["ndwi"].notna().any():
        n = float(seg["ndwi"].mean())
        nb = float(ts[ts["polygon_id"] == event["polygon_id"]]["ndwi"].mean())
        add("ndwi", (n - nb) * 100, "подтверждение" if n < nb else "слабый", "down" if n < nb else "up")

    # классификация сценария §18
    rain_neg = any(f["signal"] == "precipitation" and f["delta_pct"] < -20 for f in factors)
    soil_neg = any(f["signal"] == "soil_moisture" and f["delta_pct"] < -15 for f in factors)
    ndwi_neg = any(f["signal"] == "ndwi" and f["direction"] == "down" for f in factors)
    dq = float(event.get("data_quality", 1.0))
    if dq < 0.5 and abs(dev) > 15:
        cause = "Возможная сенсорная/облачная артефактная аномалия — проверьте качество данных"
        conf = 0.55
    elif rain_neg and soil_neg:
        cause = "Гидрологический стресс (засуха)"
        conf = 0.82
    elif ndwi_neg and dev < -10:
        cause = "Вегетационный стресс с водным компонентом"
        conf = 0.74
    elif event.get("neighbour_deviation", 0) is not None and dev < -12 and abs(float(event.get("neighbour_deviation", 0))) < 5:
        cause = "Локальная проблема поля (соседние поля в норме)"
        conf = 0.71
    elif dev < -10:
        cause = "Агростресс неустановленной природы — требуется полевая проверка"
        conf = 0.6
    else:
        cause = "Умеренное отклонение в пределах естественной изменчивости"
        conf = 0.5
    if not weather_available:
        conf = round(conf * 0.9, 2)

    period = f"{event['start_date']} — {event['end_date']}"
    narrative = (
        f"NDVI {dev:.0f}% относительно сезонной нормы за период {period}. "
        f"Наиболее вероятный фактор: {cause.lower()}. "
        + (" ".join(f"{f['signal']} {f['delta_pct']:+.0f}% ({f['strength']});" for f in factors) if factors else "Погодное подтверждение недоступно.")
        + " Это аналитическая оценка, а не агрономический диагноз."
    )
    return {
        "polygon_id": event["polygon_id"],
        "period": period,
        "headline": f"NDVI на {dev:.0f}% ниже сезонной нормы",
        "likely_cause": cause,
        "confidence": round(float(conf), 2),
        "factors": factors,
        "narrative": narrative,
        "weather_unavailable": not weather_available,
    }
