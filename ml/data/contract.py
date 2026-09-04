"""Единый data contract VEGA (§7, §27).

Все компоненты (pipelines -> features -> ML -> API -> UI) обмениваются
этой схемой. Комментарии на русском — только там, где нужен контекст.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Целевая колонка конкурсной задачи A — восстановление пропусков.
TARGET_COL = "primary_ndvi"

# Ожидаемые колонки временного ряда одного полигона.
OBS_COLUMNS: list[str] = [
    "polygon_id",
    "date",
    "primary_ndvi",
    "evi",
    "ndwi",
    "temperature",
    "precipitation",
    "soil_moisture",
    "radiation",
    "humidity",
    "cloud_fraction",
    "data_quality",
]

# Метаданные обработки (сквозная прослеживаемость).
META_COLUMNS: list[str] = [
    "is_synthetic_gap",
    "provider",
    "processing_version",
]

PROCESSING_VERSION = "v1"

# Алиасы входных датасетов (конкурсный train/test могут называть колонки иначе).
COLUMN_ALIASES: dict[str, str] = {
    "anon_polygon_id": "polygon_id",
    "field_id": "polygon_id",
    "ndvi": "primary_ndvi",
    "t2m": "temperature",
    "temp": "temperature",
    "rain": "precipitation",
    "precip": "precipitation",
}


def normalize_columns(df):
    """Приводит имена колонок конкурсного CSV к внутреннему контракту."""
    import pandas as pd  # локальный импорт — модуль должен грузиться без pandas при сборке docs

    out = df.copy()
    out.columns = [str(c).strip().lower() for c in out.columns]
    for src, dst in COLUMN_ALIASES.items():
        if src in out.columns and dst not in out.columns:
            out = out.rename(columns={src: dst})
    if "polygon_id" in out.columns:
        out["polygon_id"] = out["polygon_id"].astype(str)
    if "date" in out.columns:
        out["date"] = pd.to_datetime(out["date"]).dt.date
    if "is_synthetic_gap" not in out.columns:
        out["is_synthetic_gap"] = False
    if "provider" not in out.columns:
        out["provider"] = "unknown"
    if "processing_version" not in out.columns:
        out["processing_version"] = PROCESSING_VERSION
    if "data_quality" not in out.columns:
        out["data_quality"] = 1.0
    return out


@dataclass
class Observation:
    """Одна запись временного ряда (§27). None = пропуск/недоступно."""

    polygon_id: str
    date: str  # YYYY-MM-DD
    ndvi: float | None = None
    evi: float | None = None
    ndwi: float | None = None
    temperature: float | None = None
    precipitation: float | None = None
    soil_moisture: float | None = None
    cloud_fraction: float | None = None
    is_synthetic_gap: bool = False
    data_quality: float = 1.0
    provider: str = "unknown"
    processing_version: str = PROCESSING_VERSION
    extra: dict = field(default_factory=dict)
