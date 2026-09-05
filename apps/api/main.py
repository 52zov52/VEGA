"""REST API VEGA (§26): регионы, полигоны, анализ, ряды, аномалии, объяснения, прогноз."""
from __future__ import annotations

import json
import math
import os
from datetime import date
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

try:  # .env для локального запуска (в docker — env_file)
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

from apps.api.schemas import AnalyzeRequest, PolygonCreate, PredictionRequest, RegionCreate, RegionSearchRequest

app = FastAPI(title="VEGA // Vegetation Intelligence", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# Хранилище полигонов: память + персистентность в JSON (переживает рестарт API;
# PostGIS-контракт — следующим шагом без смены API).
_POLYGONS: dict[str, dict] = {}
_ANALYSES: dict[str, dict] = {}
_POLYGONS_FILE = Path(os.getenv("POLYGONS_FILE", "./data/polygons.json"))


def _persist_polygons() -> None:
    try:
        _POLYGONS_FILE.parent.mkdir(parents=True, exist_ok=True)
        _POLYGONS_FILE.write_text(json.dumps(list(_POLYGONS.values()), ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass  # read-only окружение — работаем в памяти


def _load_polygons() -> None:
    try:
        if _POLYGONS_FILE.exists():
            for p in json.loads(_POLYGONS_FILE.read_text(encoding="utf-8")):
                if isinstance(p, dict) and p.get("id"):
                    _POLYGONS[p["id"]] = p
    except Exception:
        pass


_load_polygons()


def _validate_ring(geometry: dict) -> list:
    """Проверяет GeoJSON Polygon, возвращает внешнее кольцо. Ошибка -> 400."""
    if not isinstance(geometry, dict) or geometry.get("type") != "Polygon":
        raise HTTPException(400, "geometry должен быть GeoJSON Polygon")
    coords = geometry.get("coordinates")
    if not isinstance(coords, list) or not coords or not isinstance(coords[0], list):
        raise HTTPException(400, "Polygon без внешнего кольца")
    ring = coords[0]
    if len(ring) < 4:
        raise HTTPException(400, "Нужно минимум 3 точки (кольцо из 4 позиций)")
    pts: list[list[float]] = []
    for p in ring:
        if not isinstance(p, (list, tuple)) or len(p) < 2:
            raise HTTPException(400, "Координата должна быть [lng, lat]")
        try:
            lng, lat = float(p[0]), float(p[1])
        except (TypeError, ValueError):
            raise HTTPException(400, "Координаты должны быть числами")
        if not (math.isfinite(lng) and math.isfinite(lat)):
            raise HTTPException(400, "Координаты должны быть конечными числами")
        if not (-180 <= lng <= 180 and -90 <= lat <= 90):
            raise HTTPException(400, "Координаты вне диапазона lng ±180 / lat ±90")
        pts.append([lng, lat])
    if pts[0] != pts[-1]:
        raise HTTPException(400, "Кольцо должно быть замкнуто (первая = последняя точка)")
    lons = [p[0] for p in pts]
    lats = [p[1] for p in pts]
    if max(lons) - min(lons) > 10 or max(lats) - min(lats) > 10:
        raise HTTPException(400, "Полигон слишком большой (сторона bbox > 10°)")
    from pipelines.geodata.fields import ring_area_ha, ring_center

    area = ring_area_ha(pts)
    if area < 0.1:
        raise HTTPException(400, "Полигон слишком маленький (< 0.1 га)")
    center = ring_center(pts)
    return pts, area, center


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "vega-api"}


@app.post("/api/regions/search")
def regions_search(body: RegionSearchRequest):
    from pipelines.geodata.fields import search_regions

    return {"regions": search_regions(body.query)}


@app.post("/api/regions")
def create_region(body: RegionCreate):
    """Новый регион в любой точке планеты: имя + центр [lat, lon]."""
    from pipelines.geodata.fields import register_region

    try:
        return register_region(body.name, body.center)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/regions/{region_id}")
def delete_region(region_id: str):
    from pipelines.geodata.fields import delete_custom_region, resolve_region

    if resolve_region(region_id) is None:
        raise HTTPException(404, "Регион не найден")
    if not delete_custom_region(region_id):
        raise HTTPException(400, "Встроенный регион удалить нельзя")
    return {"deleted": region_id}


@app.get("/api/regions/{region_id}/fields")
def region_fields(region_id: str, limit: int = 200):
    from pipelines.geodata.fields import get_fields, resolve_region

    fields, source = get_fields(region_id, limit)
    if not fields and resolve_region(region_id) is None:
        raise HTTPException(404, "Регион не найден")
    return {"region_id": region_id, "source": source, "count": len(fields), "fields": fields}


@app.post("/api/polygons")
def create_polygon(body: PolygonCreate):
    ring, area, center = _validate_ring(body.geometry)
    pid = f"AOI-{uuid4().hex[:5].upper()}"
    _POLYGONS[pid] = {"id": pid, "region_id": body.region_id, "name": body.name or pid,
                      "geometry": {"type": "Polygon", "coordinates": [ring]},
                      "crop": body.crop, "area_ha": area, "center": center}
    _persist_polygons()
    return _POLYGONS[pid]


class PolygonPatch(BaseModel):
    name: str | None = None
    crop: str | None = None


@app.patch("/api/polygons/{pid}")
def rename_polygon(pid: str, body: PolygonPatch):
    if pid not in _POLYGONS:
        raise HTTPException(404, "Полигон не найден")
    if body.name is not None:
        name = body.name.strip()
        if not name or len(name) > 80:
            raise HTTPException(400, "Название: 1–80 символов")
        _POLYGONS[pid]["name"] = name
    if body.crop is not None:
        _POLYGONS[pid]["crop"] = body.crop
    _persist_polygons()
    return _POLYGONS[pid]


@app.get("/api/polygons")
def list_polygons():
    return {"polygons": list(_POLYGONS.values())}


@app.delete("/api/polygons/{pid}")
def delete_polygon(pid: str):
    if pid not in _POLYGONS:
        raise HTTPException(404, "Полигон не найден")
    del _POLYGONS[pid]
    _persist_polygons()
    return {"deleted": pid}


@app.post("/api/analyze")
def analyze(body: AnalyzeRequest):
    from apps.api.engine import run_analysis

    pid = body.polygon_id or f"AOI-{uuid4().hex[:5].upper()}"
    geometry = body.geometry
    if geometry is None and body.polygon_id:
        # геометрия для провайдеров, которым нужен контур (Sentinel Hub):
        # сначала свои полигоны, затем контуры региона
        if body.polygon_id in _POLYGONS:
            geometry = _POLYGONS[body.polygon_id].get("geometry")
        elif body.region_id:
            try:
                from pipelines.geodata.fields import get_fields

                for f in get_fields(body.region_id, 200)[0]:
                    if f["id"] == body.polygon_id and f.get("geometry"):
                        geometry = f["geometry"]
                        break
            except Exception:
                pass
    polygon = {"id": pid, "geometry": geometry}
    start = body.start or date(2023, 1, 1)
    end = body.end or date(2024, 12, 31)
    result = run_analysis(polygon, start, end, lat=body.lat or 47.2, lon=body.lon or 39.7)
    aid = uuid4().hex[:12]
    _ANALYSES[aid] = {"id": aid, "polygon_id": polygon["id"], **result}
    return {"analysis_id": aid, "polygon_id": polygon["id"], "kpi": result["kpi"],
            "sources": result["sources"], "warnings": result["warnings"], "stats": result["stats"]}


@app.get("/api/analyze/{aid}/timeseries")
def get_timeseries(aid: str):
    if aid not in _ANALYSES:
        raise HTTPException(404, "Анализ не найден")
    return {"timeseries": _ANALYSES[aid]["timeseries"]}


@app.get("/api/analyze/{aid}/anomalies")
def get_anomalies(aid: str):
    if aid not in _ANALYSES:
        raise HTTPException(404, "Анализ не найден")
    return {"anomalies": _ANALYSES[aid]["anomalies"]}


@app.get("/api/analyze/{aid}/explanation")
def get_explanation(aid: str):
    if aid not in _ANALYSES:
        raise HTTPException(404, "Анализ не найден")
    return {"explanations": _ANALYSES[aid]["explanations"]}


@app.get("/api/analyze/{aid}/forecast")
def get_forecast(aid: str, horizon: int = 14):
    """Прогноз NDVI на horizon шагов вперёд (экспериментальный)."""
    if aid not in _ANALYSES:
        raise HTTPException(404, "Анализ не найден")
    from apps.api.engine import forecast_from_timeseries

    try:
        fc = forecast_from_timeseries(_ANALYSES[aid]["timeseries"], horizon)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"forecast": fc, "experimental": True}


@app.post("/api/prediction")
def prediction(body: PredictionRequest):
    """Восстановление одной скрытой точки primary_ndvi контекстом прошлого."""
    from apps.api.engine import _load_artifacts

    artifacts = _load_artifacts()
    if artifacts is None:
        raise HTTPException(503, "Модель не обучена: запустите scripts/train.py")
    import pandas as pd

    from ml.data.contract import TARGET_COL
    from ml.inference.predict import predict_gaps

    ctx = pd.DataFrame(body.context) if body.context else pd.DataFrame(
        [{"polygon_id": body.polygon_id, "date": str(body.date), TARGET_COL: None}])
    if TARGET_COL not in ctx.columns and "ndvi" in ctx.columns:
        ctx = ctx.rename(columns={"ndvi": TARGET_COL})
    ctx["polygon_id"] = body.polygon_id
    filled = predict_gaps(ctx, artifacts)
    val = float(filled.iloc[-1]) if len(filled) else float("nan")
    return {"polygon_id": body.polygon_id, "date": str(body.date), "primary_ndvi_pred": round(val, 6)}
