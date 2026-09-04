"""Абстракция спутниковых провайдеров (§5) с fallback на кэш/demo (§35)."""
from __future__ import annotations

import hashlib
import json
import os
from abc import ABC, abstractmethod
from datetime import date
from pathlib import Path

import pandas as pd

CACHE_DIR = Path(os.getenv("CACHE_DIR", "./data/cache"))
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def cache_key(polygon: dict, start: str, end: str, source: str, version: str) -> str:
    raw = json.dumps({"polygon": polygon, "start": start, "end": end,
                      "source": source, "version": version}, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


class SatelliteProvider(ABC):
    name = "base"

    @abstractmethod
    def fetch(self, polygon: dict, start: date, end: date) -> pd.DataFrame:
        raise NotImplementedError


class Sentinel2Provider(SatelliteProvider):
    name = "sentinel-2"

    def fetch(self, polygon: dict, start: date, end: date) -> pd.DataFrame:
        url = os.getenv("SENTINEL_API_URL", "")
        key = os.getenv("SENTINEL_API_KEY", "")
        if not url or not key:
            raise RuntimeError("Sentinel provider unavailable (нет URL/ключа)")
        import httpx  # реальный запрос; в demo упадёт в fallback выше по стеку

        r = httpx.post(url, json={"polygon": polygon, "start": str(start), "end": str(end)},
                       headers={"Authorization": f"Bearer {key}"}, timeout=30)
        r.raise_for_status()
        return pd.DataFrame(r.json())


class LandsatProvider(SatelliteProvider):
    name = "landsat-8/9"

    def fetch(self, polygon: dict, start: date, end: date) -> pd.DataFrame:
        raise RuntimeError("Landsat provider unavailable (offline demo режим)")


class ModisProvider(SatelliteProvider):
    name = "modis"

    def fetch(self, polygon: dict, start: date, end: date) -> pd.DataFrame:
        raise RuntimeError("MODIS provider unavailable (offline demo режим)")


class DemoSatelliteProvider(SatelliteProvider):
    """Детерминированный demo-провайдер: тот же генератор, что и ML-dataset."""

    name = "demo"

    def fetch(self, polygon: dict, start: date, end: date) -> pd.DataFrame:
        from ml.data.dataset import generate_demo_dataset

        pid = polygon.get("id", "AOI-00001")
        df = generate_demo_dataset(n_polygons=3, start=str(start), end=str(end), seed=abs(hash(pid)) % 10_000)
        df["polygon_id"] = pid
        return df


def fetch_satellite(polygon: dict, start: date, end: date, version: str = "v1") -> tuple[pd.DataFrame, str]:
    """Пробует провайдеры по порядку, затем кэш, затем demo. Никогда не бросает 500 наружу."""
    key = cache_key(polygon, str(start), str(end), "sat", version)
    cache_file = CACHE_DIR / f"sat_{key}.parquet"
    if cache_file.exists():
        try:
            return pd.read_parquet(cache_file), "cache"
        except Exception:
            pass
    for provider in (Sentinel2Provider(), LandsatProvider(), ModisProvider()):
        try:
            df = provider.fetch(polygon, start, end)
            try:
                df.to_parquet(cache_file, index=False)
            except Exception:
                pass
            return df, provider.name
        except Exception:
            continue
    # fallback: demo + пометка источника
    df = DemoSatelliteProvider().fetch(polygon, start, end)
    df["provider"] = "demo(fallback)"
    return df, "demo(fallback)"
