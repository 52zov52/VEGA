"""Тесты конвейера данных: выбор эндпоинта, fallback-цепочки, статистика (§35)."""
from datetime import date

import pandas as pd

import pipelines.weather.providers as W


def test_open_meteo_url_selection(monkeypatch):
    monkeypatch.delenv("WEATHER_API_URL", raising=False)
    assert "archive" in W.open_meteo_url(date(2023, 5, 1), date(2023, 9, 30))
    assert "forecast" in W.open_meteo_url(date(2100, 1, 1), date(2100, 1, 5))
    # значение по умолчанию из .env — тоже «авто», а не принудительный forecast
    monkeypatch.setenv("WEATHER_API_URL", W.FORECAST_URL)
    assert "archive" in W.open_meteo_url(date(2023, 5, 1), date(2023, 5, 2))
    monkeypatch.setenv("WEATHER_API_URL", "https://proxy.local/wm")
    assert W.open_meteo_url(date(2023, 5, 1), date(2023, 5, 2)) == "https://proxy.local/wm"


def test_power_parsing(monkeypatch):
    import httpx

    payload = {"properties": {"parameter": {
        "T2M": {"20230601": 20.0, "20230602": 21.0},
        "PRECTOTCORR": {"20230601": 0.0, "20230602": 5.0},
        "RH2M": {"20230601": 60.0, "20230602": 65.0},
        "ALLSKY_SFC_SW_DWN": {"20230601": 25.0, "20230602": 26.0},
        "GWETTOP": {"20230601": 0.4, "20230602": -999},
    }}}

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return payload

    monkeypatch.setattr(httpx, "get", lambda *a, **k: Resp())
    df = W.PowerProvider().fetch(47.2, 39.7, date(2023, 6, 1), date(2023, 6, 2))
    assert len(df) == 2 and df["temperature"].iloc[0] == 20.0
    assert pd.isna(df["soil_moisture"].iloc[1])  # -999 -> пропуск, а не 0


def test_weather_fallback_chain(monkeypatch):
    monkeypatch.setattr(W.OpenMeteoProvider, "fetch", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    sentinel = pd.DataFrame({"date": [date(2023, 6, 1)], "temperature": [20.0],
                             "precipitation": [0.0], "soil_moisture": [0.3],
                             "radiation": [25.0], "humidity": [60.0]})
    monkeypatch.setattr(W.PowerProvider, "fetch", lambda *a, **k: sentinel)
    df, ok, src = W.fetch_weather(47.2, 39.7, date(2023, 6, 1), date(2023, 6, 2))
    assert ok and src == "nasa-power" and len(df) == 1
    # тотальный отказ — satellite-only, без исключений
    monkeypatch.setattr(W.PowerProvider, "fetch", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    df, ok, src = W.fetch_weather(47.2, 39.7, date(2023, 6, 1), date(2023, 6, 2))
    assert df is None and not ok and src == "satellite-only"


def test_satellite_total_outage_falls_back_to_demo(monkeypatch):
    import pipelines.satellite.providers as S

    monkeypatch.delenv("SENTINEL_API_URL", raising=False)
    monkeypatch.delenv("SENTINEL_API_KEY", raising=False)
    monkeypatch.delenv("SENTINEL_SH_CLIENT_ID", raising=False)
    monkeypatch.delenv("SENTINEL_SH_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("OVERPASS_API_URL", raising=False)
    poly = {"id": "TEST-NO-SATELLITE-UNIQUE"}
    df, source = S.fetch_satellite(poly, date(2023, 5, 1), date(2023, 5, 31), version="pytest")
    assert source == "demo(fallback)" and len(df) > 0
    assert (df["provider"] == "demo(fallback)").all()


def test_sentinel_hub_parsing(monkeypatch):
    import httpx

    import pipelines.satellite.providers as S

    monkeypatch.setenv("SENTINEL_SH_CLIENT_ID", "id")
    monkeypatch.setenv("SENTINEL_SH_CLIENT_SECRET", "secret")
    monkeypatch.setattr(S.SentinelHubStatProvider, "_get_token", classmethod(lambda cls, c, s: "tok"))

    def fake_post(url, **kwargs):
        assert "statistics" in url

        class Resp:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                def band(mean, sc=8, nod=2):
                    return {"stats": {"mean": mean, "sampleCount": sc, "noDataCount": nod}}

                return {"data": [
                    {"interval": {"from": "2023-06-01T00:00:00Z"},
                     "outputs": {"default": {"bands": {
                         "B0": band(0.62), "B1": band(0.5), "B2": band(0.1)}}}},
                    {"interval": {"from": "2023-06-08T00:00:00Z"},
                     "outputs": {"default": {"bands": {
                         "B0": {"stats": {"mean": "NaN"}}, "B1": band(0.5), "B2": band(0.1)}}}},
                ]}

        return Resp()

    monkeypatch.setattr(httpx, "post", fake_post)
    poly = {"id": "P1", "geometry": {"type": "Polygon",
                                     "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}}
    df = S.SentinelHubStatProvider().fetch(poly, date(2023, 6, 1), date(2023, 6, 30))
    assert len(df) == 1  # второй слот без mean отброшен
    assert abs(df["primary_ndvi"].iloc[0] - 0.62) < 1e-9
    assert abs(df["data_quality"].iloc[0] - 0.8) < 1e-9


def test_sentinel_hub_retry_on_throttle(monkeypatch):
    import time

    import httpx

    import pipelines.satellite.providers as S

    monkeypatch.setenv("SENTINEL_SH_CLIENT_ID", "id")
    monkeypatch.setenv("SENTINEL_SH_CLIENT_SECRET", "secret")
    monkeypatch.setattr(S.SentinelHubStatProvider, "_get_token", classmethod(lambda cls, c, s: "tok"))
    monkeypatch.setattr(time, "sleep", lambda *a, **k: None)
    calls = []

    def band(mean):
        return {"stats": {"mean": mean, "sampleCount": 8, "noDataCount": 2}}

    class Resp:
        def __init__(self, status):
            self.status_code = status

        def raise_for_status(self):
            if self.status_code != 200:
                raise httpx.HTTPStatusError("x", request=None, response=self)

        def json(self):
            bands = {"B0": band(0.6), "B1": band(0.5), "B2": band(0.1)}
            slot = {"interval": {"from": "2023-06-01T00:00:00Z"},
                    "outputs": {"default": {"bands": bands}}}
            return {"data": [slot]}

    def fake_post(url, **kwargs):
        calls.append(url)
        if len(calls) == 1:
            return Resp(429)  # троттлинг — должен повторить, а не упасть в demo
        return Resp(200)

    monkeypatch.setattr(httpx, "post", fake_post)
    poly = {"id": "P1", "geometry": {"type": "Polygon",
                                     "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}}
    df = S.SentinelHubStatProvider().fetch(poly, date(2023, 6, 1), date(2023, 6, 30))
    assert len(calls) == 2 and len(df) == 1
    assert S.SentinelHubStatProvider.last_error in (None, "")


def test_analyze_returns_pipeline_stats():
    from fastapi.testclient import TestClient

    from apps.api.main import app

    r = TestClient(app).post("/api/analyze", json={
        "polygon_id": "AOI-00001", "start": "2023-05-01", "end": "2023-05-31",
        "lat": 47.2, "lon": 39.7}).json()
    assert set(("points", "gaps_filled", "date_min", "date_max")) <= set(r["stats"])
    assert r["stats"]["points"] > 0
    assert set(("satellite", "weather", "restore")) <= set(r["sources"])
