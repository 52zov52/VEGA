"""Абстракция спутниковых провайдеров (§5) с fallback на кэш/demo (§35)."""
from __future__ import annotations

import hashlib
import json
import math
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
        urls = [u.strip() for u in os.getenv("SENTINEL_API_URL", "").split(",") if u.strip()]
        key = os.getenv("SENTINEL_API_KEY", "")
        if not urls or not key:
            raise RuntimeError("Sentinel provider unavailable (нет URL/ключа)")
        import httpx  # реальный запрос; в demo упадёт в fallback выше по стеку

        last: Exception | None = None
        for url in urls:  # зеркала по порядку + ретрай
            for _ in range(2):
                try:
                    r = httpx.post(url, json={"polygon": polygon, "start": str(start), "end": str(end)},
                                   headers={"Authorization": f"Bearer {key}"}, timeout=30)
                    r.raise_for_status()
                    return pd.DataFrame(r.json())
                except Exception as e:  # noqa: BLE001
                    last = e
        raise RuntimeError(f"Sentinel unavailable: {last}")


class LandsatProvider(SatelliteProvider):
    name = "landsat-8/9"

    def fetch(self, polygon: dict, start: date, end: date) -> pd.DataFrame:
        raise RuntimeError("Landsat provider unavailable (offline demo режим)")


class ModisProvider(SatelliteProvider):
    name = "modis"

    def fetch(self, polygon: dict, start: date, end: date) -> pd.DataFrame:
        raise RuntimeError("MODIS provider unavailable (offline demo режим)")


class SentinelHubStatProvider(SatelliteProvider):
    """Sentinel-2 L2A через Sentinel Hub Statistical API (CDSE).

    Сервер сам считает зональную статистику NDVI/EVI/NDWI по полигону со
    SCL-маской облаков — скачивать сцены не нужно. Требует OAuth-клиент:
    SENTINEL_SH_CLIENT_ID + SENTINEL_SH_CLIENT_SECRET.
    Без них — молча пропускает дальше по цепочке (не ошибка).
    """

    name = "sentinel-2-sh"
    TOKEN_URL = ("https://identity.dataspace.copernicus.eu/auth/realms/CDSE/"
                 "protocol/openid-connect/token")
    STAT_URL = "https://sh.dataspace.copernicus.eu/api/v1/statistics"
    EVALSCRIPT = (
        "//VERSION=3\n"
        "function setup(){return{input:[\"B04\",\"B08\",\"B02\",\"B11\",\"SCL\",\"dataMask\"],"
        "output:[{id:\"default\",bands:3,sampleType:\"FLOAT32\"},{id:\"dataMask\",bands:1}]}}"
        "function evaluatePixel(s){"
        "var veg=(s.SCL==4||s.SCL==5)?1:0;"
        "if(!veg)return{default:[NaN,NaN,NaN],dataMask:[0]};"
        "var ndvi=(s.B08-s.B04)/(s.B08+s.B04);"
        "var evi=2.5*(s.B08-s.B04)/(s.B08+6*s.B04-7.5*s.B02+1);"
        "var ndwi=(s.B08-s.B11)/(s.B08+s.B11);"
        "return{default:[ndvi,evi,ndwi],dataMask:[s.dataMask]};}"
    )
    _token: str | None = None
    _token_exp: float = 0.0
    # Последняя причина недоступности — движок показывает её в warnings,
    # чтобы было видно ПОЧЕМУ fallback, а не просто факт.
    last_error: str | None = None

    @classmethod
    def _get_token(cls, cid: str, secret: str) -> str:
        import time

        import httpx

        if cls._token and time.time() < cls._token_exp - 60:
            return cls._token
        r = httpx.post(cls.TOKEN_URL, data={
            "grant_type": "client_credentials",
            "client_id": cid, "client_secret": secret,
        }, timeout=30)
        r.raise_for_status()
        j = r.json()
        cls._token = j["access_token"]
        cls._token_exp = time.time() + int(j.get("expires_in", 3600))
        return cls._token

    def fetch(self, polygon: dict, start: date, end: date) -> pd.DataFrame:
        import time

        import httpx

        type(self).last_error = None
        cid = os.getenv("SENTINEL_SH_CLIENT_ID", "")
        secret = os.getenv("SENTINEL_SH_CLIENT_SECRET", "")
        if not cid or not secret:
            raise RuntimeError("Sentinel Hub: нет credentials (пропускаем)")
        geom = (polygon.get("geometry") or {})
        if geom.get("type") != "Polygon" or not (geom.get("coordinates") or [None])[0]:
            type(self).last_error = "у полигона нет геометрии"
            raise RuntimeError("Sentinel Hub: полигону нужна геометрия")
        frm, to = f"{start}T00:00:00Z", f"{end}T23:59:59Z"
        payload = {
            "input": {"bounds": {"geometry": geom}, "data": [{
                "type": "sentinel-2-l2a",
                "dataFilter": {"timeRange": {"from": frm, "to": to}, "maxCloudCoverage": 95}}]},
            "aggregation": {"timeRange": {"from": frm, "to": to},
                            "aggregationInterval": {"of": "P7D"},
                            "evalscript": self.EVALSCRIPT, "width": 256, "height": 256},
            "calculations": {"default": {}},
        }

        def once(token: str):
            return httpx.post(self.STAT_URL, json=payload,
                              headers={"Authorization": f"Bearer {token}"}, timeout=120)

        last: Exception | None = None
        for attempt in range(3):
            try:
                token = self._get_token(cid, secret)
                r = once(token)
                if r.status_code == 401 and attempt == 0:
                    # протухший кэшированный токен — обновляем и повторяем сразу
                    type(self)._token, type(self)._token_exp = None, 0.0
                    continue
                if r.status_code in (429, 503, 504) and attempt < 2:
                    # троттлинг/перегруз CDSE — пауза и повтор
                    time.sleep(5 * (attempt + 1))
                    continue
                r.raise_for_status()
                break
            except Exception as e:  # noqa: BLE001
                last = e
                if attempt < 2:
                    time.sleep(2)
        else:
            type(self).last_error = str(last)[:200] if last else "неизвестная ошибка"
            raise RuntimeError(f"Sentinel Hub недоступен: {type(self).last_error}")
        try:
            return self._parse(polygon, r.json())
        except Exception as e:  # noqa: BLE001
            type(self).last_error = f"некорректный ответ API: {e}"[:200]
            raise RuntimeError(f"Sentinel Hub: {type(self).last_error}")

    @staticmethod
    def _parse(polygon: dict, body: dict) -> pd.DataFrame:
        rows = []
        for slot in body.get("data", []):
            out = (slot.get("outputs") or {}).get("default") or {}
            bands = out.get("bands") or {}
            stats = [(bands.get(f"B{i}") or {}).get("stats") or {} for i in range(3)]
            try:
                means = [float(s.get("mean")) for s in stats]
            except (TypeError, ValueError):
                continue
            # mean может прийти строкой "NaN" (неделя сплошь в облаках) — пропуск
            if any(not math.isfinite(m) for m in means):
                continue
            sc = stats[0].get("sampleCount", 0) or 0
            nodata = stats[0].get("noDataCount", 0) or 0
            tot = sc + nodata
            day = str((slot.get("interval") or {}).get("from", ""))[:10]
            if not day:
                continue
            rows.append({"polygon_id": polygon.get("id", "AOI-00001"), "date": day,
                         "primary_ndvi": round(means[0], 5),
                         "evi": round(means[1], 5), "ndwi": round(means[2], 5),
                         "data_quality": round(1 - nodata / tot, 3) if tot else 0.5,
                         "provider": "sentinel-2-sh"})
        if not rows:
            raise RuntimeError("Sentinel Hub: пустой ряд (все даты в облаках?)")
        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"]).dt.date
        return df


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
    for provider in (SentinelHubStatProvider(), Sentinel2Provider(), LandsatProvider(), ModisProvider()):
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
