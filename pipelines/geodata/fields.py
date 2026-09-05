"""Поиск сельхозконтуров: Overpass/OSM + ESA WorldCover fallback на demo-сетку (§19)."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
from uuid import uuid4

REGIONS = {
    # Агрорегионы РФ с реальными центрами (центры — областные центры, для
    # автопоиска контуров точности достаточно: радиус 20–30 км).
    "rostov": {"name": "Ростовская область", "bbox": [38.0, 46.0, 44.0, 48.5], "center": [47.2, 39.7]},
    "krasnodar": {"name": "Краснодарский край", "bbox": [37.0, 43.5, 41.5, 46.5], "center": [45.0, 39.0]},
    "voronezh": {"name": "Воронежская область", "bbox": [38.0, 49.5, 43.0, 52.0], "center": [51.6, 39.2]},
    "stavropol": {"name": "Ставропольский край", "center": [45.045, 41.973]},
    "volgograd": {"name": "Волгоградская область", "center": [48.708, 44.513]},
    "saratov": {"name": "Саратовская область", "center": [51.592, 46.034]},
    "samara": {"name": "Самарская область", "center": [53.195, 50.101]},
    "orenburg": {"name": "Оренбургская область", "center": [51.768, 55.097]},
    "tatarstan": {"name": "Республика Татарстан", "center": [55.788, 49.122]},
    "bashkortostan": {"name": "Республика Башкортостан", "center": [54.738, 55.972]},
    "belgorod": {"name": "Белгородская область", "center": [50.610, 36.580]},
    "kursk": {"name": "Курская область", "center": [51.730, 35.187]},
    "oryol": {"name": "Орловская область", "center": [52.967, 36.069]},
    "lipetsk": {"name": "Липецкая область", "center": [52.608, 39.572]},
    "tambov": {"name": "Тамбовская область", "center": [52.723, 41.452]},
    "penza": {"name": "Пензенская область", "center": [53.195, 45.004]},
    "ulyanovsk": {"name": "Ульяновская область", "center": [54.314, 48.403]},
    "ryazan": {"name": "Рязанская область", "center": [54.629, 39.741]},
    "tula": {"name": "Тульская область", "center": [54.193, 37.617]},
    "bryansk": {"name": "Брянская область", "center": [53.243, 34.363]},
    "astrakhan": {"name": "Астраханская область", "center": [46.349, 48.032]},
    "kalmykia": {"name": "Республика Калмыкия", "center": [46.308, 44.270]},
    "kurgan": {"name": "Курганская область", "center": [55.458, 65.341]},
    "chelyabinsk": {"name": "Челябинская область", "center": [55.159, 61.402]},
    "omsk": {"name": "Омская область", "center": [54.991, 73.364]},
    "novosibirsk": {"name": "Новосибирская область", "center": [55.028, 82.921]},
    "altai": {"name": "Алтайский край", "center": [53.354, 83.769]},
}

# Пользовательские регионы: любая точка планеты, не только 3 preset'а.
# Оба пути получения контуров (Overpass around + demo-сетка) работают от центра,
# поэтому кастомный регион сразу полноценный: контуры, перелёт камеры, анализ.
_CUSTOM: dict[str, dict] = {}
_REGIONS_FILE = Path(os.getenv("REGIONS_FILE", "./data/regions.json"))


def _persist_custom() -> None:
    try:
        _REGIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
        _REGIONS_FILE.write_text(json.dumps(list(_CUSTOM.values()), ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _load_custom() -> None:
    try:
        if _REGIONS_FILE.exists():
            for r in json.loads(_REGIONS_FILE.read_text(encoding="utf-8")):
                if isinstance(r, dict) and r.get("id") and r.get("center"):
                    _CUSTOM[r["id"]] = r
    except Exception:
        pass


_load_custom()


def resolve_region(region_id: str) -> dict | None:
    if region_id in REGIONS:
        return {"id": region_id, **REGIONS[region_id]}
    return _CUSTOM.get(region_id)


def register_region(name: str, center: list[float]) -> dict:
    """Новый регион по центру [lat, lon]. Ошибки значений -> ValueError."""
    name = (name or "").strip()
    if not (1 <= len(name) <= 80):
        raise ValueError("Название региона: 1–80 символов")
    try:
        lat, lon = float(center[0]), float(center[1])
    except (TypeError, ValueError, IndexError):
        raise ValueError("Центр должен быть [lat, lon] числами")
    if not (math.isfinite(lat) and math.isfinite(lon)):
        raise ValueError("Центр должен быть конечными числами")
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("Центр вне диапазона lat ±90 / lon ±180")
    rid = f"custom-{uuid4().hex[:6]}"
    _CUSTOM[rid] = {"id": rid, "name": name, "center": [round(lat, 6), round(lon, 6)]}
    _persist_custom()
    return _CUSTOM[rid]


def delete_custom_region(region_id: str) -> bool:
    if region_id in REGIONS:
        return False  # встроенные удалять нельзя
    if region_id in _CUSTOM:
        del _CUSTOM[region_id]
        _persist_custom()
        return True
    return False

# Радиус автопоиска вокруг центра региона: весь bbox региона для Overpass
# слишком велик (таймауты), ищем поля рядом с центром — их и показываем первыми.
OVERPASS_RADIUS_M = int(os.getenv("OVERPASS_RADIUS_M", "20000"))


def search_regions(query: str) -> list[dict]:
    q = (query or "").strip().lower()
    out = []
    for rid, meta in list(REGIONS.items()) + [(r["id"], r) for r in _CUSTOM.values()]:
        rid_s = rid if isinstance(rid, str) else meta.get("id", "")
        if not q or q in rid_s.lower() or q in str(meta.get("name", "")).lower():
            out.append({"id": rid_s, **{k: v for k, v in meta.items() if k != "id"}})
    # живой геокодер OSM: любой регион мира по названию (с троттлингом и кэшем)
    if len(q) >= 2:
        try:
            out += search_nominatim(q)
        except Exception:
            pass
    seen, uniq = set(), []
    for r in out:
        if r["id"] not in seen:
            seen.add(r["id"])
            uniq.append(r)
    return uniq


_NOMINATIM_CACHE: dict[str, list[dict]] = {}
_NOMINATIM_LAST: float = 0.0


def search_nominatim(query: str, limit: int = 5) -> list[dict]:
    """Nominatim (OSM): название -> центр+bbox. Лимит 1 запр/с, кэш, timeout."""
    import time

    import httpx

    global _NOMINATIM_LAST
    key = query.strip().lower()
    if key in _NOMINATIM_CACHE:
        return _NOMINATIM_CACHE[key]
    wait = 1.1 - (time.time() - _NOMINATIM_LAST)
    if wait > 0:
        time.sleep(wait)
    base = os.getenv("NOMINATIM_URL", "https://nominatim.openstreetmap.org/search")
    r = httpx.get(base, params={"q": query.strip(), "format": "jsonv2", "limit": limit},
                  headers={"Accept-Language": "ru", "User-Agent": "VEGA-hackathon/1.0"},
                  timeout=10)
    _NOMINATIM_LAST = time.time()
    r.raise_for_status()
    out = []
    for e in r.json():
        try:
            lat, lon = float(e["lat"]), float(e["lon"])
            s, n, w, ee = (float(x) for x in e.get("boundingbox", [lat, lat, lon, lon]))
            name = str(e.get("display_name", "")).split(",")[:2]
            out.append({"id": f"osm-{e.get('place_id')}", "name": ", ".join(name).strip() or str(e.get("name", "")),
                        "center": [round(lat, 6), round(lon, 6)],
                        "bbox": [round(w, 6), round(s, 6), round(ee, 6), round(n, 6)],
                        "source": "nominatim"})
        except (TypeError, ValueError, KeyError):
            continue
    _NOMINATIM_CACHE[key] = out
    return out


def ring_area_ha(ring: list) -> float:
    """Площадь кольца [lng, lat] в гектарах (равнопромежуточная аппроксимация)."""
    pts = [(float(p[0]), float(p[1])) for p in ring
           if isinstance(p, (list, tuple)) and len(p) >= 2]
    if len(pts) < 3:
        return 0.0
    s = sum(pts[i][0] * pts[i + 1][1] - pts[i + 1][0] * pts[i][1] for i in range(len(pts) - 1))
    mean_lat = sum(p[1] for p in pts) / len(pts) * math.pi / 180
    deg2 = (111.32 ** 2) * max(math.cos(mean_lat), 0.2)
    return round(abs(s) / 2 * deg2 * 100, 2)


def ring_center(ring: list) -> list[float]:
    pts = [(float(p[0]), float(p[1])) for p in ring
           if isinstance(p, (list, tuple)) and len(p) >= 2]
    if not pts:
        return [0.0, 0.0]
    # центр bbox — устойчивее среднего при неравномерных кольцах OSM
    lons = [p[0] for p in pts]
    lats = [p[1] for p in pts]
    lat_c = (min(lats) + max(lats)) / 2
    lon_c = (min(lons) + max(lons)) / 2
    return [round(lat_c, 6), round(lon_c, 6)]


def _parse_overpass(elements: list, region_id: str, limit: int) -> list[dict]:
    """Элементы Overpass (out geom) -> поля с настоящей геометрией."""
    fields = []
    for e in elements:
        geom = e.get("geometry") or []
        ring = [[float(p["lon"]), float(p["lat"])] for p in geom
                if isinstance(p, dict) and "lon" in p and "lat" in p]
        if len(ring) < 4:
            continue
        if len(ring) > 2000:
            continue  # гигантские кольца — не поля, а артефакты/леса
        if ring[0] != ring[-1]:
            ring = ring + [ring[0]]
        area = ring_area_ha(ring)
        if not (1.0 <= area <= 20000.0):
            continue
        tags = e.get("tags") or {}
        fields.append({
            "id": f"FLD-{e.get('id')}",
            "region_id": region_id,
            "area_ha": area,
            "crop": tags.get("crop", "unknown"),
            "center": ring_center(ring),
            "geometry": {"type": "Polygon", "coordinates": [ring]},
        })
        if len(fields) >= limit:
            break
    return fields


def fetch_overpass(region_id: str, limit: int) -> list[dict]:
    """Реальные контуры farmland рядом с центром региона. Бросает исключение —
    вызывающий решает fallback (никогда не 500 наружу).

    OVERPASS_API_URL может содержать несколько зеркал через запятую.
    Зеркала опрашиваются ПАРАЛЛЕЛЬНО (гонка): публичные инстансы вечерами
    лежат/троттлят по очереди, первый успех побеждает — это в разы надёжнее
    и быстрее последовательного перебора с таймаутами.
    """
    import httpx
    from concurrent.futures import ThreadPoolExecutor, as_completed

    meta = resolve_region(region_id)
    if meta is None:
        raise RuntimeError(f"Регион не найден: {region_id}")
    lat0, lon0 = meta["center"]
    ql = (f"[out:json][timeout:20];"
          f"way[\"landuse\"=\"farmland\"](around:{OVERPASS_RADIUS_M},{lat0},{lon0});"
          f"out geom {limit};")
    urls = [u.strip() for u in os.getenv("OVERPASS_API_URL", "").split(",") if u.strip()]
    if not urls:
        raise RuntimeError("Overpass: нет URL")

    def hit(url: str) -> list[dict]:
        r = httpx.post(url, content=ql, timeout=30)
        r.raise_for_status()
        return _parse_overpass(r.json().get("elements", []), region_id, limit)

    errors: list[str] = []
    pool = ThreadPoolExecutor(max_workers=min(len(urls), 4))
    try:
        futures = {pool.submit(hit, u): u for u in urls}
        for fut in as_completed(futures):
            try:
                fields = fut.result()
                if fields:
                    return fields
            except Exception as e:  # noqa: BLE001 — зеркало легло, ждём следующее
                errors.append(f"{futures[fut]}: {e}")
    finally:
        # не ждём проигравшие зеркала (у них свои timeout'ы, до 30с фоном)
        pool.shutdown(wait=False, cancel_futures=True)
    raise RuntimeError(f"Overpass недоступен: {'; '.join(errors)[:300]}")


FIELDS_CACHE_TTL = int(os.getenv("FIELDS_CACHE_TTL_SECONDS", "604800"))


def _fields_cache_path(region_id: str, limit: int) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in region_id)[:64]
    d = Path(os.getenv("CACHE_DIR", "./data/cache"))
    d.mkdir(parents=True, exist_ok=True)
    return d / f"fields_{safe}_{limit}.json"


def get_fields(region_id: str, limit: int = 200) -> tuple[list[dict], str]:
    """Возвращает (поля, источник). Свежий кэш -> Overpass -> протухший кэш -> demo.

    Demo-fallback специально НЕ кэшируем: иначе одна неудача приклеит
    квадраты на весь TTL, даже когда Overpass уже ожил.
    """
    meta = resolve_region(region_id)
    if meta is None:
        return [], "none"
    stale: list[dict] = []
    if FIELDS_CACHE_TTL > 0:
        try:
            p = _fields_cache_path(region_id, limit)
            if p.exists():
                import time

                cached = json.loads(p.read_text(encoding="utf-8"))
                if cached.get("source") == "overpass" and cached.get("fields"):
                    if time.time() - cached.get("ts", 0) < FIELDS_CACHE_TTL:
                        return cached["fields"], "overpass"
                    stale = cached["fields"]
        except Exception:
            pass
    if os.getenv("OVERPASS_API_URL", ""):
        try:
            fields = fetch_overpass(region_id, limit)
            if fields:
                if FIELDS_CACHE_TTL > 0:
                    try:
                        import time

                        _fields_cache_path(region_id, limit).write_text(
                            json.dumps({"ts": time.time(), "source": "overpass", "fields": fields},
                                       ensure_ascii=False), encoding="utf-8")
                    except Exception:
                        pass
                return fields, "overpass"
        except Exception:
            pass
    if stale:
        return stale, "overpass-cache"
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
    # demo НЕ кэшируем (см. docstring выше)
    return fields, "demo"
