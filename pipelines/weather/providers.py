"""Погодный провайдер: Open-Meteo (ERA5) с satellite-only fallback (§35)."""
from __future__ import annotations

import os
from datetime import date

import pandas as pd


class WeatherProvider:
    name = "open-meteo"

    def fetch(self, lat: float, lon: float, start: date, end: date) -> pd.DataFrame:
        base = os.getenv("WEATHER_API_URL", "https://api.open-meteo.com/v1/forecast")
        try:
            import httpx

            params = {"latitude": lat, "longitude": lon, "start_date": str(start), "end_date": str(end),
                      "daily": "temperature_2m_mean,precipitation_sum,soil_moisture_3_9cm,shortwave_radiation_sum,relative_humidity_2m_mean",
                      "timezone": "auto"}
            r = httpx.get(base, params=params, timeout=30)
            r.raise_for_status()
            j = r.json().get("daily", {})
            return pd.DataFrame({
                "date": pd.to_datetime(j.get("time", [])).date,
                "temperature": j.get("temperature_2m_mean", []),
                "precipitation": j.get("precipitation_sum", []),
                "soil_moisture": j.get("soil_moisture_3_9cm", []),
                "radiation": j.get("shortwave_radiation_sum", []),
                "humidity": j.get("relative_humidity_2m_mean", []),
            })
        except Exception as e:  # noqa: BLE001 — сеть недоступна, переключаемся в satellite-only
            raise RuntimeError(f"Weather unavailable: {e}") from e


def fetch_weather(lat: float, lon: float, start: date, end: date) -> tuple[pd.DataFrame | None, bool]:
    """Возвращает (df_or_None, weather_available). Никогда не падает."""
    try:
        return WeatherProvider().fetch(lat, lon, start, end), True
    except Exception:
        return None, False
