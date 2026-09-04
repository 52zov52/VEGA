"""Сквозной analysis engine: регион/полигон -> данные -> ряд -> восстановление -> аномалии (§2)."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import joblib
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
    # 3. погода
    weather_df, weather_ok = fetch_weather(lat, lon, start, end)
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
    timeseries = [{
        "date": str(r["date"]), "ndvi_observed": _f(r.get(TARGET_COL)),
        "ndvi_restored": _f(r.get(TARGET_COL)), "ndvi_climatology": _f(r.get("clim_mean")),
        "evi": _f(r.get("evi")), "ndwi": _f(r.get("ndwi")),
        "precipitation": _f(r.get("precipitation")), "anomaly": bool(r.get("level") in ("stress", "critical")),
    } for _, r in scored.sort_values("date").tail(400).iterrows()]
    return {"kpi": kpi, "timeseries": timeseries, "anomalies": events,
            "explanations": explanations, "warnings": warnings,
            "sources": {"satellite": sat_source, "weather": "open-meteo" if weather_ok else "satellite-only",
                        "restore": restore_method}}


def _f(v) -> float | None:
    try:
        f = float(v)
        return round(f, 4) if pd.notna(v) else None
    except (TypeError, ValueError):
        return None
