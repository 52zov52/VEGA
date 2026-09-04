"""Схемы запросов/ответов REST API (§26)."""
from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, Field


class RegionSearchRequest(BaseModel):
    query: str = ""


class PolygonCreate(BaseModel):
    region_id: str | None = None
    name: str | None = None
    geometry: dict = Field(description="GeoJSON Polygon")
    crop: str | None = None


class AnalyzeRequest(BaseModel):
    polygon_id: str | None = None
    geometry: dict | None = None
    region_id: str | None = None
    start: date | None = None
    end: date | None = None
    lat: float | None = None
    lon: float | None = None


class PredictionRequest(BaseModel):
    polygon_id: str
    date: date
    context: list[dict[str, Any]] = Field(default_factory=list)
