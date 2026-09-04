"""Тесты аномалий и объяснений: засуха vs локальная vs сенсорная (§18)."""
import pandas as pd

from ml.data.contract import TARGET_COL
from ml.data.dataset import generate_demo_dataset
from services.anomaly.detector import detect_anomalies
from services.climatology.climatology import build_climatology
from services.explanation.explainer import explain_event


def _drought_case() -> pd.DataFrame:
    df = generate_demo_dataset(n_polygons=2, start="2023-01-01", end="2023-12-31", seed=7)
    # искусственная засуха на первом полигоне в июле: NDVI/NDWI вниз, дождь 0, жара
    pid = "AOI-00001"
    m = (df["polygon_id"] == pid) & (pd.to_datetime(df["date"]).dt.month == 7)
    df.loc[m, TARGET_COL] -= 0.25
    df.loc[m, "evi"] -= 0.2
    df.loc[m, "ndwi"] -= 0.2
    df.loc[m, "precipitation"] = 0.0
    df.loc[m, "temperature"] += 6.0
    df.loc[m, "soil_moisture"] -= 0.15
    return df


def test_drought_detected_and_explained():
    df = _drought_case()
    scored, events = detect_anomalies(df, build_climatology(df))
    mine = [e for e in events if e["polygon_id"] == "AOI-00001"]
    assert len(mine) >= 1, "Засуха должна детектироваться"
    exp = explain_event(mine[0], scored.rename(columns={TARGET_COL: "primary_ndvi"}))
    assert "засух" in exp["likely_cause"].lower() or "стресс" in exp["likely_cause"].lower()
    assert exp["confidence"] >= 0.5
