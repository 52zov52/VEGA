"""REST API VEGA (§26): регионы, полигоны, анализ, ряды, аномалии, объяснения, прогноз."""
from __future__ import annotations

from datetime import date
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from apps.api.schemas import AnalyzeRequest, PolygonCreate, PredictionRequest, RegionSearchRequest

app = FastAPI(title="VEGA // Vegetation Intelligence", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# In-memory хранилище полигонов (заменяется PostGIS без смены контракта)
_POLYGONS: dict[str, dict] = {}
_ANALYSES: dict[str, dict] = {}


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "vega-api"}


@app.post("/api/regions/search")
def regions_search(body: RegionSearchRequest):
    from pipelines.geodata.fields import search_regions

    return {"regions": search_regions(body.query)}


@app.get("/api/regions/{region_id}/fields")
def region_fields(region_id: str, limit: int = 200):
    from pipelines.geodata.fields import get_fields

    fields, source = get_fields(region_id, limit)
    if not fields and region_id not in ("rostov", "krasnodar", "voronezh"):
        raise HTTPException(404, "Регион не найден")
    return {"region_id": region_id, "source": source, "count": len(fields), "fields": fields}


@app.post("/api/polygons")
def create_polygon(body: PolygonCreate):
    pid = f"AOI-{uuid4().hex[:5].upper()}"
    _POLYGONS[pid] = {"id": pid, "region_id": body.region_id, "name": body.name or pid,
                      "geometry": body.geometry, "crop": body.crop}
    return _POLYGONS[pid]


@app.get("/api/polygons")
def list_polygons():
    return {"polygons": list(_POLYGONS.values())}


@app.delete("/api/polygons/{pid}")
def delete_polygon(pid: str):
    if pid not in _POLYGONS:
        raise HTTPException(404, "Полигон не найден")
    del _POLYGONS[pid]
    return {"deleted": pid}


@app.post("/api/analyze")
def analyze(body: AnalyzeRequest):
    from apps.api.engine import run_analysis

    polygon = {"id": body.polygon_id or f"AOI-{uuid4().hex[:5].upper()}", "geometry": body.geometry}
    start = body.start or date(2023, 1, 1)
    end = body.end or date(2024, 12, 31)
    result = run_analysis(polygon, start, end, lat=body.lat or 47.2, lon=body.lon or 39.7)
    aid = uuid4().hex[:12]
    _ANALYSES[aid] = {"id": aid, "polygon_id": polygon["id"], **result}
    return {"analysis_id": aid, "polygon_id": polygon["id"], "kpi": result["kpi"],
            "sources": result["sources"], "warnings": result["warnings"]}


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
