"""Проба Sentinel Hub: токен + ряд NDVI по тестовому квадрату (Ростов).

Креды читает из .env (SENTINEL_SH_CLIENT_ID / SENTINEL_SH_CLIENT_SECRET).
Использование: py scripts/sentinel_probe.py
"""
import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if (ROOT / ".env").exists():
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

from pipelines.satellite.providers import SentinelHubStatProvider

lon, lat, s = 39.7, 47.2, 0.02
ring = [
    [lon - s, lat - s], [lon + s, lat - s], [lon + s, lat + s],
    [lon - s, lat + s], [lon - s, lat - s],
]
poly = {"id": "PROBE-ROSTOV",
        "geometry": {"type": "Polygon", "coordinates": [ring]}}
try:
    df = SentinelHubStatProvider().fetch(poly, date(2023, 6, 1), date(2023, 6, 30))
except Exception as e:
    print(f"FAIL: {type(e).__name__}: {str(e)[:300]}")
    raise SystemExit(1)
print(f"OK: {len(df)} точек")
print(df.to_string())
