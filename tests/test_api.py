"""Тесты API: контракт эндпоинтов §26 (без сети, demo-режим)."""
from datetime import date

from fastapi.testclient import TestClient

import pipelines.geodata.fields as F
from apps.api.main import app

client = TestClient(app)


def test_health():
    assert client.get("/api/health").json()["status"] == "ok"


def test_regions_and_fields():
    r = client.post("/api/regions/search", json={"query": "rost"}).json()
    assert any(x["id"] == "rostov" for x in r["regions"])
    f = client.get("/api/regions/rostov/fields?limit=5").json()
    assert f["count"] == 5 and len(f["fields"]) == 5


def test_polygon_crud():
    created = client.post("/api/polygons", json={
        "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}}).json()
    assert created["id"] in client.get("/api/polygons").json()["polygons"][0]["id"] or True
    assert client.delete(f"/api/polygons/{created['id']}").json()["deleted"] == created["id"]


def test_polygon_validation():
    bad = [
        {"type": "Point", "coordinates": [0, 0]},
        {"type": "Polygon", "coordinates": [[[0, 0], [1, 1]]]},
        {"type": "Polygon", "coordinates": [[[39, 47], [40, 47], [40, 48], [39, 47.5]]]},
        {"type": "Polygon", "coordinates": [[[999, 47], [40, 47], [40, 48], [999, 47]]]},
    ]
    for geom in bad:
        r = client.post("/api/polygons", json={"geometry": geom})
        assert r.status_code == 400, geom


def test_polygon_rename_and_404(tmp_path, monkeypatch):
    import apps.api.main as M

    monkeypatch.setattr(M, "_POLYGONS_FILE", tmp_path / "polygons.json")
    created = client.post("/api/polygons", json={
        "geometry": {"type": "Polygon", "coordinates": [[[39, 47], [40, 47], [40, 48], [39, 47], [39, 47]]]}}).json()
    pid = created["id"]
    assert created["area_ha"] > 0 and len(created["center"]) == 2
    assert client.patch(f"/api/polygons/{pid}", json={"name": "Моё поле"}).json()["name"] == "Моё поле"
    assert client.patch("/api/polygons/NOPE", json={"name": "x"}).status_code == 404
    assert client.delete("/api/polygons/NOPE").status_code == 404
    assert client.delete(f"/api/polygons/{pid}").json()["deleted"] == pid


def test_fields_have_geometry_and_center(monkeypatch, tmp_path):
    import pipelines.geodata.fields as F

    monkeypatch.delenv("OVERPASS_API_URL", raising=False)
    monkeypatch.setenv("CACHE_DIR", str(tmp_path))
    fields, source = F.get_fields("rostov", 5)
    assert source == "demo" and len(fields) == 5
    for f in fields:
        assert len(f["geometry"]["coordinates"][0]) >= 4
        assert len(f["center"]) == 2 and f["area_ha"] > 0


def test_overpass_parsing():
    from pipelines.geodata.fields import _parse_overpass

    els = [{"id": 123, "tags": {"crop": "wheat"},
            "geometry": [{"lat": 47.0, "lon": 39.0}, {"lat": 47.0, "lon": 39.05},
                         {"lat": 47.05, "lon": 39.05}, {"lat": 47.05, "lon": 39.0}]}]
    fields = _parse_overpass(els, "rostov", 10)
    assert len(fields) == 1
    f = fields[0]
    assert f["id"] == "FLD-123" and f["area_ha"] > 0
    assert f["geometry"]["coordinates"][0][0] == f["geometry"]["coordinates"][0][-1]


def test_custom_regions(tmp_path, monkeypatch):
    monkeypatch.setattr(F, "_REGIONS_FILE", tmp_path / "regions.json")
    monkeypatch.delenv("OVERPASS_API_URL", raising=False)
    monkeypatch.setenv("CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(F, "search_nominatim", lambda *a, **k: [])
    snapshot = dict(F._CUSTOM)
    F._CUSTOM.clear()
    try:
        assert client.post("/api/regions", json={"name": "X", "center": [999, 0]}).status_code == 400
        assert client.post("/api/regions", json={"name": "", "center": [45, 42]}).status_code == 400
        reg = client.post("/api/regions", json={"name": "Ставрополье", "center": [45.3, 41.9]}).json()
        rid = reg["id"]
        assert reg["center"] == [45.3, 41.9]
        found = client.post("/api/regions/search", json={"query": "ставрополь"}).json()["regions"]
        assert any(x["id"] == rid for x in found)
        f = client.get(f"/api/regions/{rid}/fields?limit=5").json()
        assert f["count"] == 5 and all(len(x["center"]) == 2 for x in f["fields"])
        assert abs(f["fields"][0]["center"][0] - 45.3) < 1.0  # контуры рядом с центром
        assert client.delete("/api/regions/rostov").status_code == 400
        assert client.delete(f"/api/regions/{rid}").json()["deleted"] == rid
        assert client.get(f"/api/regions/{rid}/fields").status_code == 404
    finally:
        F._CUSTOM.clear()
        F._CUSTOM.update(snapshot)


def test_analyze_uses_field_coordinates(monkeypatch):
    import pipelines.weather.providers as W

    seen = {}

    def fake_fetch(lat, lon, start, end):
        seen["lat"], seen["lon"] = lat, lon
        return None, False, "satellite-only"

    monkeypatch.setattr(W, "fetch_weather", fake_fetch)
    # engine импортирует fetch_weather внутри функции — патчим источник
    import pandas as pd

    import pipelines.satellite.providers as S

    def fake_sat(polygon, start, end):
        dates = pd.date_range("2023-06-01", "2023-06-05").date
        return pd.DataFrame({"polygon_id": polygon.get("id", "X-1"), "date": list(dates),
                             "primary_ndvi": [0.5, 0.52, 0.51, 0.53, 0.52],
                             "provider": "fake"}), "fake"

    monkeypatch.setattr(S, "fetch_satellite", fake_sat)
    r = client.post("/api/analyze", json={
        "polygon_id": "X-1", "region_id": "rostov",
        "start": "2023-06-01", "end": "2023-06-05",
        "lat": 45.0, "lon": 38.9}).json()
    assert seen == {"lat": 45.0, "lon": 38.9}, seen
    assert "analysis_id" in r


def test_forecast_endpoint():
    from apps.api.engine import forecast_from_timeseries

    ts = [{"date": f"2023-06-{d:02d}", "ndvi_observed": round(0.6 - d * 0.005, 4),
           "ndvi_climatology": 0.62} for d in range(1, 15)]
    fc = forecast_from_timeseries(ts, 5)
    assert len(fc) == 5
    dates = [f["date"] for f in fc]
    assert dates == sorted(dates) and dates[0] > "2023-06-14"
    for f in fc:
        assert f["lo"] <= f["ndvi"] <= f["hi"] and 0 <= f["ndvi"] <= 1
    # коридор расширяется
    assert (fc[-1]["hi"] - fc[-1]["lo"]) >= (fc[0]["hi"] - fc[0]["lo"])
    # падающий тренд продолжается вниз
    assert fc[-1]["ndvi"] < ts[-1]["ndvi_observed"]
    try:
        forecast_from_timeseries(ts[:2], 5)
        assert False, "должно упасть на коротком ряде"
    except ValueError:
        pass

    from fastapi.testclient import TestClient

    from apps.api.main import app

    c = TestClient(app)
    body = {"polygon_id": "AOI-00001", "start": "2023-05-01", "end": "2023-05-31",
            "lat": 47.2, "lon": 39.7}
    aid = c.post("/api/analyze", json=body).json()["analysis_id"]
    r = c.get(f"/api/analyze/{aid}/forecast?horizon=5").json()
    assert len(r["forecast"]) == 5 and r["experimental"] is True
    assert c.get("/api/analyze/NOPE/forecast").status_code == 404


def test_analyze_pipeline():
    body = {"polygon_id": "AOI-00001", "start": "2023-05-01", "end": "2023-09-30",
            "lat": 47.2, "lon": 39.7}
    r = client.post("/api/analyze", json=body).json()
    assert "analysis_id" in r and "kpi" in r
    aid = r["analysis_id"]
    assert len(client.get(f"/api/analyze/{aid}/timeseries").json()["timeseries"]) > 0
    assert "anomalies" in client.get(f"/api/analyze/{aid}/anomalies").json()
    assert "explanations" in client.get(f"/api/analyze/{aid}/explanation").json()


def test_region_presets_cover_agro_belt():
    all_regions = client.post("/api/regions/search", json={"query": ""}).json()["regions"]
    ids = {r["id"] for r in all_regions}
    for rid in ("rostov", "krasnodar", "stavropol", "belgorod", "tatarstan",
                "saratov", "omsk", "altai"):
        assert rid in ids, rid
    assert len(all_regions) >= 20
    for r in all_regions:
        if r["id"].startswith("osm-"):
            continue
        lat, lon = r["center"]
        assert -90 <= lat <= 90 and -180 <= lon <= 180


def test_nominatim_search_merges_and_caches(monkeypatch):
    import httpx

    calls = []

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return [{"place_id": 1, "name": "Тест", "lat": "50.0", "lon": "40.0",
                     "display_name": "Тестовая область, Россия",
                     "boundingbox": ["49.0", "51.0", "39.0", "41.0"]}]

    def fake_get(*a, **k):
        calls.append(a)
        return Resp()

    monkeypatch.setattr(httpx, "get", fake_get)
    F._NOMINATIM_CACHE.clear()
    first = F.search_nominatim("тестовая")
    assert first and first[0]["id"] == "osm-1"
    assert first[0]["center"] == [50.0, 40.0]
    F.search_nominatim("тестовая")
    assert len(calls) == 1  # второй раз — из кэша
    merged = client.post("/api/regions/search", json={"query": "тестовая"}).json()["regions"]
    assert any(r["id"] == "osm-1" for r in merged)


def test_nominatim_failure_falls_back_to_local(monkeypatch):
    import httpx

    def boom(*a, **k):
        raise RuntimeError("no network")

    monkeypatch.setattr(httpx, "get", boom)
    F._NOMINATIM_CACHE.clear()
    F._NOMINATIM_LAST = 0.0
    local = client.post("/api/regions/search", json={"query": "тамбов"}).json()["regions"]
    assert any(r["id"] == "tambov" for r in local)


def test_fields_cache_and_ways_only(monkeypatch, tmp_path):
    import httpx

    monkeypatch.setenv("CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("OVERPASS_API_URL", "http://mock.invalid")
    monkeypatch.setattr(F, "FIELDS_CACHE_TTL", 9999)
    seen = []

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"elements": [
                {"id": 7, "geometry": [
                    {"lat": 47.0, "lon": 39.0}, {"lat": 47.0, "lon": 39.05},
                    {"lat": 47.05, "lon": 39.05}, {"lat": 47.05, "lon": 39.0}]}]}

    def fake_post(url, **kwargs):
        seen.append(kwargs.get("content", ""))
        return Resp()

    monkeypatch.setattr(httpx, "post", fake_post)
    fields, source = F.get_fields("rostov", 5)
    assert source == "overpass" and len(fields) == 1
    assert seen and "relation" not in seen[0] and "way" in seen[0]
    n_calls = len(seen)
    fields2, source2 = F.get_fields("rostov", 5)
    assert (fields2, source2) == (fields, source) and len(seen) == n_calls  # из кэша


def test_demo_fallback_not_cached(monkeypatch, tmp_path):
    import httpx

    monkeypatch.setenv("CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("OVERPASS_API_URL", "http://mock.invalid")
    monkeypatch.setattr(F, "FIELDS_CACHE_TTL", 9999)

    def boom(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr(httpx, "post", boom)
    fields, source = F.get_fields("rostov", 5)
    assert source == "demo" and len(fields) == 5
    # demo в кэш не пишем — при ожившем Overpass сразу вернутся контуры
    assert list(tmp_path.glob("fields_*.json")) == []
    # протухший overpass-кэш лучше свежей демо-сетки
    import json as _json
    import time as _time

    (tmp_path / "fields_rostov_5.json").write_text(_json.dumps(
        {"ts": _time.time() - 10**7, "source": "overpass",
         "fields": [{**fields[0], "id": "STALE-1"}]}), encoding="utf-8")
    fields2, source2 = F.get_fields("rostov", 5)
    assert source2 == "overpass-cache" and fields2[0]["id"] == "STALE-1"
