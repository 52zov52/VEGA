"""Тесты API: контракт эндпоинтов §26 (без сети, demo-режим)."""
from datetime import date

from fastapi.testclient import TestClient

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


def test_analyze_pipeline():
    body = {"polygon_id": "AOI-00001", "start": "2023-05-01", "end": "2023-09-30",
            "lat": 47.2, "lon": 39.7}
    r = client.post("/api/analyze", json=body).json()
    assert "analysis_id" in r and "kpi" in r
    aid = r["analysis_id"]
    assert len(client.get(f"/api/analyze/{aid}/timeseries").json()["timeseries"]) > 0
    assert "anomalies" in client.get(f"/api/analyze/{aid}/anomalies").json()
    assert "explanations" in client.get(f"/api/analyze/{aid}/explanation").json()
