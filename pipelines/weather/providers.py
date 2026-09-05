"""Погодные провайдеры: Open-Meteo (ERA5-архив для прошлого / прогноз для свежих дат)
+ NASA POWER (независимый fallback, тоже без ключей) + satellite-only режим (§35)."""
from __future__ import annotations

import os
from datetime import date, timedelta

import pandas as pd

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
POWER_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"

_DAILY = ("temperature_2m_mean,precipitation_sum,soil_moisture_3_9cm,"
          "shortwave_radiation_sum,relative_humidity_2m_mean")


def open_meteo_url(start: date, end: date) -> str:
    """Прошлое — ERA5-архив, свежие даты — прогноз (у прогноза нет истории).

    Кастомный WEATHER_API_URL имеет приоритет — кроме значения по умолчанию
    (forecast): оно эквивалентно «авто», чтобы исторические окна уходили в архив.
    """
    custom = os.getenv("WEATHER_API_URL", "")
    if custom and custom != FORECAST_URL:
        return custom
    if end < date.today() - timedelta(days=10):
        return ARCHIVE_URL
    return FORECAST_URL


class OpenMeteoProvider:
    name = "open-meteo"

    def fetch(self, lat: float, lon: float, start: date, end: date) -> pd.DataFrame:
        import httpx

        params = {"latitude": lat, "longitude": lon, "start_date": str(start), "end_date": str(end),
                  "daily": _DAILY, "timezone": "auto"}
        last: Exception | None = None
        for _ in range(2):  # ретрай на сетевые сбои
            try:
                r = httpx.get(open_meteo_url(start, end), params=params, timeout=30)
                r.raise_for_status()
                j = r.json().get("daily", {})
                if not j.get("time"):
                    raise RuntimeError("Open-Meteo: пустой daily")
                return pd.DataFrame({
                    "date": pd.to_datetime(j.get("time", [])).date,
                    "temperature": j.get("temperature_2m_mean", []),
                    "precipitation": j.get("precipitation_sum", []),
                    "soil_moisture": j.get("soil_moisture_3_9cm", []),
                    "radiation": j.get("shortwave_radiation_sum", []),
                    "humidity": j.get("relative_humidity_2m_mean", []),
                })
            except Exception as e:  # noqa: BLE001
                last = e
        raise RuntimeError(f"Open-Meteo unavailable: {last}")


class PowerProvider:
    """NASA POWER daily point (AG) — независимый источник, без ключей."""

    name = "nasa-power"

    def fetch(self, lat: float, lon: float, start: date, end: date) -> pd.DataFrame:
        import httpx

        params = {"parameters": "T2M,PRECTOTCORR,RH2M,ALLSKY_SFC_SW_DWN,GWETTOP",
                  "community": "AG", "longitude": lon, "latitude": lat,
                  "start": start.strftime("%Y%m%d"), "end": end.strftime("%Y%m%d"),
                  "format": "JSON"}
        r = httpx.get(POWER_URL, params=params, timeout=30)
        r.raise_for_status()
        props = r.json().get("properties", {}).get("parameter", {})
        if not props.get("T2M"):
            raise RuntimeError("POWER: пустой ответ")
        days = sorted(props["T2M"].keys())

        def col(key: str):
            vals = []
            for d in days:
                v = props.get(key, {}).get(d, -999)
                vals.append(None if v in (-999, None) else v)
            return vals

        return pd.DataFrame({
            "date": pd.to_datetime(days).date,
            "temperature": col("T2M"),
            "precipitation": col("PRECTOTCORR"),
            "soil_moisture": col("GWETTOP"),
            "radiation": col("ALLSKY_SFC_SW_DWN"),
            "humidity": col("RH2M"),
        })


def fetch_weather(lat: float, lon: float, start: date, end: date) -> tuple[pd.DataFrame | None, bool, str]:
    """Возвращает (df_or_None, available, source_name). Никогда не падает."""
    for provider in (OpenMeteoProvider(), PowerProvider()):
        try:
            return provider.fetch(lat, lon, start, end), True, provider.name
        except Exception:
            continue
    return None, False, "satellite-only"
