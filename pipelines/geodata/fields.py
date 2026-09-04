"""Поиск сельхозконтуров: Overpass/OSM + ESA WorldCover fallback на demo-сетку (§19)."""
from __future__ import annotations

import os

REGIONS = {
    "rostov": {"name": "Rostov region", "bbox": [38.0, 46.0, 44.0, 48.5], "center": [47.2, 39.7]},
    "krasnodar": {"name": "Krasnodar region", "bbox": [37.0, 43.5, 41.5, 46.5], "center": [45.0, 39.0]},
    "voronezh": {"name": "Voronezh region", "bbox": [38.0, 49.5, 43.0, 52.0], "center": [51.6, 39.2]},
}


def search_regions(query: str) -> list[dict]:
    q = (query or "").strip().lower()
    out = []
    for rid, meta in REGIONS.items():
        if not q or q in rid or q in meta["name"].lower():
            out.append({"id": rid, **meta})
    return out


def get_fields(region_id: str, limit: int = 200) -> tuple[list[dict], str]:
    """Возвращает (поля, источник). Пробует Overpass, иначе demo-контуры."""
    meta = REGIONS.get(region_id)
    if meta is None:
        return [], "none"
    overpass = os.getenv("OVERPASS_API_URL", "")
    if overpass:
        try:
            import httpx

            bbox = meta["bbox"]
            ql = (f"[out:json][timeout:25];(way[\"landuse\"=\"farmland\"]"
                  f"({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]}););out geom {limit};")
            r = httpx.post(overpass, content=ql, timeout=30)
            r.raise_for_status()
            els = r.json().get("elements", [])[:limit]
            fields = [{"id": f"FLD-{e.get('id')}", "region_id": region_id,
                       "area_ha": 50.0, "crop": "unknown",
                       "geometry": {"type": "Polygon", "coordinates": []}} for e in els]
            if fields:
                return fields, "overpass"
        except Exception:
            pass
    # demo-контуры: регулярная сетка вокруг центра региона
    import hashlib

    lat0, lon0 = meta["center"]
    h = int(hashlib.sha256(region_id.encode()).hexdigest(), 16)
    fields = []
    for i in range(min(limit, 60)):
        dlat = ((h >> (i % 8)) % 40 - 20) / 100
        dlon = ((h >> ((i + 3) % 8)) % 40 - 20) / 100
        lat, lon = lat0 + dlat + (i // 10) * 0.08, lon0 + dlon + (i % 10) * 0.08
        s = 0.02
        fields.append({
            "id": f"{region_id.upper()}-{i + 1:04d}",
            "region_id": region_id,
            "area_ha": round(30 + (h + i * 37) % 270, 1),
            "crop": ["winter wheat", "sunflower", "corn", "barley"][i % 4],
            "center": [lat, lon],
            "geometry": {"type": "Polygon", "coordinates": [[[lon - s, lat - s], [lon + s, lat - s],
                                                             [lon + s, lat + s], [lon - s, lat + s],
                                                             [lon - s, lat - s]]]},
        })
    return fields, "demo"
