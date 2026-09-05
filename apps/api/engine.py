"""Сквозной analysis engine: регион/полигон -> данные -> ряд -> восстановление -> аномалии (§2)."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import joblib
import math
import numpy as np
import pandas as pd

MODEL_DIR = Path("./models")


def _load_artifacts():
    if not (MODEL_DIR / "gbm.joblib").exists():
        return None
    try:
        from ml.inference.predict import load_artifacts

        return load_artifacts(MODEL_DIR)
    except Exception:
        return None


def run_analysis(polygon: dict, start: date, end: date, lat: float = 47.2, lon: float = 39.7) -> dict:
    """Полный pipeline с fallback-ами: никогда не возвращает 500, а частичный результат."""
    from ml.data.contract import TARGET_COL
    from ml.models.baselines import baseline_linear
    from pipelines.preprocessing.clean import preprocess_observations
    from pipelines.satellite.providers import fetch_satellite
    from pipelines.weather.providers import fetch_weather
    from services.climatology.climatology import build_climatology
    from services.anomaly.detector import detect_anomalies
    from services.explanation.explainer import explain_event

    warnings: list[str] = []
    # 1-2. сбор спутниковых данных
    try:
        sat_df, sat_source = fetch_satellite(polygon, start, end)
    except Exception as e:  # noqa: BLE001
        warnings.append(f"Satellite provider unavailable, demo fallback: {e}")
        from ml.data.dataset import generate_demo_dataset

        sat_df = generate_demo_dataset(n_polygons=1, start=str(start), end=str(end))
        sat_df["polygon_id"] = polygon.get("id", "AOI-00001")
        sat_source = "demo(fallback)"
    if sat_source.startswith("demo"):
        warnings.append("Использован demo-источник спутниковых данных (offline режим)")
        try:
            from pipelines.satellite.providers import SentinelHubStatProvider

            reason = SentinelHubStatProvider.last_error
            if reason:
                warnings.append(f"Sentinel Hub недоступен ({reason}) — показан demo-ряд")
        except Exception:
            pass
    # 3. погода: Open-Meteo (архив/прогноз) -> NASA POWER -> satellite-only
    weather_df, weather_ok, weather_source = fetch_weather(lat, lon, start, end)
    if not weather_ok:
        warnings.append("Weather confirmation unavailable — anomaly engine в satellite-only режиме")
    elif weather_df is not None and len(weather_df):
        weather_df["date"] = pd.to_datetime(weather_df["date"]).dt.date
        sat_df["date"] = pd.to_datetime(sat_df["date"]).dt.date
        sat_df = sat_df.merge(weather_df, on="date", how="left", suffixes=("", "_wx"))
        for c in ("temperature", "precipitation", "soil_moisture", "radiation", "humidity"):
            wx = f"{c}_wx"
            if wx in sat_df.columns:
                sat_df[c] = sat_df[c].fillna(sat_df[wx]) if c in sat_df.columns else sat_df[wx]
    # 4. очистка
    clean = preprocess_observations(sat_df)
    # 5. восстановление пропусков: обученная модель или линейный fallback
    artifacts = _load_artifacts()
    restored = clean.copy()
    if artifacts is not None:
        try:
            from ml.inference.predict import predict_gaps

            restored[TARGET_COL] = predict_gaps(clean, artifacts)
            restore_method = f"ensemble({artifacts['gbm'].used_backend}+{artifacts['temporal'].used_backend}+seasonal)"
        except Exception as e:  # noqa: BLE001
            warnings.append(f"Model inference failed, linear fallback: {e}")
            restored[TARGET_COL] = clean.groupby("polygon_id")[TARGET_COL].transform(
                lambda s: baseline_linear(s))
            restore_method = "linear(fallback)"
    else:
        restored[TARGET_COL] = clean.groupby("polygon_id")[TARGET_COL].transform(lambda s: baseline_linear(s))
        restore_method = "linear(no-model)"
    # 6. климатология + аномалии
    clim = build_climatology(restored)
    scored, events = detect_anomalies(restored, clim)
    # сначала тяжёлые: critical > stress > watch, внутри — по оценке
    rank = {"critical": 0, "stress": 1, "watch": 2}
    events = sorted(events, key=lambda e: (rank.get(e.get("level", "watch"), 3), -float(e.get("anomaly_score", 0))))
    explanations = [explain_event(e, scored.rename(columns={TARGET_COL: "primary_ndvi"}),
                                  weather_available=weather_ok) for e in events[:10]]
    # KPI для карточки поля (§21)
    latest = scored.sort_values("date").iloc[-1] if len(scored) else None
    kpi = {}
    if latest is not None:
        kpi = {
            "current_ndvi": round(float(latest[TARGET_COL]), 3) if pd.notna(latest[TARGET_COL]) else None,
            "season_deviation_pct": round(float(latest.get("deviation_pct", 0)), 1),
            "anomaly_score": round(float(latest.get("anomaly_score", 0)), 3),
            "data_quality": round(float(latest.get("data_quality", 1.0)), 3),
            "level": str(latest.get("level", "normal")),
        }
        # NaN не сериализуется в JSON (был 500 на крошечных окнах) — только null
        kpi = {k: (None if isinstance(v, float) and not math.isfinite(v) else v)
               for k, v in kpi.items()}
    timeseries = [{
        "date": str(r["date"]), "ndvi_observed": _f(r.get(TARGET_COL)),
        "ndvi_restored": _f(r.get(TARGET_COL)), "ndvi_climatology": _f(r.get("clim_mean")),
        "evi": _f(r.get("evi")), "ndwi": _f(r.get("ndwi")),
        "precipitation": _f(r.get("precipitation")), "anomaly": bool(r.get("level") in ("stress", "critical")),
    } for _, r in scored.sort_values("date").tail(400).iterrows()]
    # статистика конвейера: сколько точек, сколько дыр закрыли, за какой период
    clean_gaps = int(clean[TARGET_COL].isna().sum()) if TARGET_COL in clean else 0
    dates = pd.to_datetime(scored["date"]) if len(scored) else pd.Series([], dtype="datetime64[ns]")
    stats = {
        "points": int(len(scored)),
        "gaps_filled": clean_gaps,
        "date_min": str(dates.min().date()) if len(dates) else None,
        "date_max": str(dates.max().date()) if len(dates) else None,
    }
    return {"kpi": kpi, "timeseries": timeseries, "anomalies": events,
            "explanations": explanations, "warnings": warnings, "stats": stats,
            "sources": {"satellite": sat_source, "weather": weather_source if weather_ok else "satellite-only",
                        "restore": restore_method}}


def _f(v) -> float | None:
    try:
        f = float(v)
        return round(f, 4) if pd.notna(v) else None
    except (TypeError, ValueError):
        return None


def forecast_from_timeseries(ts: list[dict], horizon: int = 14) -> list[dict]:
    """Краткосрочный прогноз NDVI (экспериментальный, §доп): недавний тренд,
    смешанный с ходом климатологии + расширяющийся коридор неопределённости.

    Не ML-модель, а прозрачная эвристика для планирования выездов:
    при устойчивом падении покажет продолжение спада, при норме — плато.
    """
    pts = [(str(p.get("date")), p.get("ndvi_observed"), p.get("ndvi_climatology"))
           for p in (ts or [])]
    pts = [(d, o, c) for d, o, c in pts
           if o is not None and pd.notna(o)]
    if len(pts) < 4:
        raise ValueError("мало точек для прогноза (нужно ≥ 4)")
    dates = pd.to_datetime([p[0] for p in pts])
    steps = np.diff(dates.values).astype("timedelta64[D]").astype(int)
    step = int(max(1, round(float(np.median(steps))))) if len(steps) else 7
    # Горизонт не дальше ~3 месяцев: прогноз на полгода вперёд (в зиму)
    # агроному бесполезен и выглядит как «линия ради линии».
    horizon = max(1, min(int(horizon), 30, max(1, 90 // step)))
    obs = np.array([float(p[1]) for p in pts[-12:]])
    x = np.arange(len(obs))
    slope = float(np.polyfit(x, obs, 1)[0]) if len(obs) >= 2 else 0.0
    slope = float(np.clip(slope, -0.05, 0.05))  # не верим в обрывы
    clim = np.array([float(p[2]) for p in pts[-12:] if p[2] is not None and pd.notna(p[2])])
    if len(clim) >= 2:
        clim_slope = float(np.polyfit(np.arange(len(clim)), clim, 1)[0])
    else:
        clim_slope = 0.0
    drift = 0.5 * slope + 0.5 * float(np.clip(clim_slope, -0.05, 0.05))
    resid = obs - np.polyval(np.polyfit(x, obs, 1), x) if len(obs) >= 3 else obs - obs.mean()
    sigma = max(float(np.std(resid)), 0.015)
    last = obs[-1]
    last_date = dates[-1]
    out = []
    for h in range(1, horizon + 1):
        v = float(np.clip(last + drift * h, 0.0, 1.0))
        w = min(0.25, sigma * (h ** 0.5) + 0.02)
        out.append({"date": str((last_date + pd.Timedelta(days=h * step)).date()),
                    "ndvi": round(v, 4),
                    "lo": round(max(0.0, v - w), 4),
                    "hi": round(min(1.0, v + w), 4)})
    return out
