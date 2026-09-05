"""Тесты аномалий и объяснений: засуха vs локальная vs сенсорная (§18)."""
import numpy as np
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


def _july(events, pid="AOI-00001"):
    out = []
    for e in events:
        if e["polygon_id"] != pid:
            continue
        days = set(pd.date_range(e["start_date"], e["end_date"], freq="D").date)
        july = set(pd.date_range("2023-07-01", "2023-07-31", freq="D").date)
        if days & july:
            out.append(e)
    return out


def test_drought_detected_and_explained():
    df = _drought_case()
    scored, events = detect_anomalies(df, build_climatology(df))
    mine = _july(events)
    assert len(mine) >= 1, "Засуха должна детектироваться"
    e = max(mine, key=lambda x: x["anomaly_score"])
    assert e["kind"] == "sustained"
    exp = explain_event(e, scored.rename(columns={TARGET_COL: "primary_ndvi"}))
    assert "засух" in exp["likely_cause"].lower() or "стресс" in exp["likely_cause"].lower()
    assert exp["confidence"] >= 0.5
    assert exp["level"] == e["level"] and exp["start_date"] == e["start_date"]


def _flat(n_days=300, seed=11):
    """Детерминированный плоский ряд: полный контроль над инъекциями."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range(start="2023-01-01", periods=n_days, freq="D")
    rows = []
    for pid in ("T-01", "T-02"):
        ndvi = 0.62 + rng.normal(0, 0.01, n_days)
        rows.append(pd.DataFrame({
            "polygon_id": pid, "date": dates.date,
            TARGET_COL: np.round(ndvi, 5),
            "evi": np.round(ndvi * 0.82, 5),
            "ndwi": np.round(0.1 + rng.normal(0, 0.008, n_days), 5),
            "temperature": np.round(20 + rng.normal(0, 1.2, n_days), 2),
            "precipitation": np.round(np.clip(rng.exponential(3.0, n_days), 0, 40), 2),
            "soil_moisture": np.round(0.3 + rng.normal(0, 0.012, n_days), 4),
            "data_quality": np.round(np.full(n_days, 0.95), 3),
        }))
    return pd.concat(rows, ignore_index=True)


def _dip(df, pid, lo, hi, d_ndvi, d_evi=0.0, quality=None):
    m = (df["polygon_id"] == pid) & (df["date"] >= pd.Timestamp(lo).date()) & (df["date"] <= pd.Timestamp(hi).date())
    idx = df.index[m]
    df.loc[idx, TARGET_COL] = (df.loc[idx, TARGET_COL] + d_ndvi).clip(0.05, 0.95)
    df.loc[idx, "evi"] = (df.loc[idx, "evi"] + d_evi).clip(0.03, 0.9)
    if quality is not None:
        df.loc[idx, "data_quality"] = quality
    return set(df.loc[idx, "date"].tolist())


def _detect(df):
    clean = df  # вызывающий строит clim сам, если нужно чисто
    return detect_anomalies(clean, build_climatology(clean))


def _overlap(ev, truth):
    days = set(pd.date_range(ev["start_date"], ev["end_date"], freq="D").date)
    return len(days & truth)


def test_watch_early_warning():
    clean = _flat()
    clim = build_climatology(clean)
    df = clean.copy()
    truth = _dip(df, "T-01", "2023-03-01", "2023-03-06", -0.05, -0.045)
    scored, events = detect_anomalies(df, clim)
    mine = [e for e in events if e["polygon_id"] == "T-01" and _overlap(e, truth) >= 1]
    assert mine, "мягкий эпизод должен давать раннее предупреждение"
    assert any(e["level"] in ("watch", "stress") for e in mine)


def test_spike_kind():
    clean = _flat()
    clim = build_climatology(clean)
    df = clean.copy()
    truth = _dip(df, "T-01", "2023-04-01", "2023-04-01", -0.25, -0.2)
    scored, events = detect_anomalies(df, clim)
    mine = [e for e in events if e["polygon_id"] == "T-01" and _overlap(e, truth) >= 1]
    assert len(mine) == 1 and mine[0]["kind"] == "spike"


def test_split_episode_merged():
    clean = _flat()
    clim = build_climatology(clean)
    df = clean.copy()
    t = _dip(df, "T-01", "2023-05-01", "2023-05-02", -0.2, -0.16)
    t |= _dip(df, "T-01", "2023-05-04", "2023-05-05", -0.2, -0.16)
    scored, events = detect_anomalies(df, clim)
    mine = [e for e in events if e["polygon_id"] == "T-01" and _overlap(e, t) >= 1]
    assert len(mine) == 1, "эпизод с просветом — одно событие"


def test_recovery_flag():
    clean = _flat()
    clim = build_climatology(clean)
    df = clean.copy()
    truth = _dip(df, "T-01", "2023-06-01", "2023-06-07", -0.2, -0.16)
    scored, events = detect_anomalies(df, clim)
    mine = [e for e in events if e["polygon_id"] == "T-01" and _overlap(e, truth) >= 2]
    assert mine and any(e["recovered"] for e in mine)
    exp = explain_event(mine[0], scored.rename(columns={TARGET_COL: "primary_ndvi"}))
    assert "вернулось" in exp["narrative"]


def test_cloudy_single_point_demoted():
    clean = _flat()
    clim = build_climatology(clean)
    df = clean.copy()
    truth = _dip(df, "T-01", "2023-07-01", "2023-07-01", -0.3, -0.25, quality=0.1)
    scored, events = detect_anomalies(df, clim)
    mine = [e for e in events if e["polygon_id"] == "T-01" and _overlap(e, truth) >= 1]
    assert mine and all(e["level"] == "watch" for e in mine), "облачный всплеск не должен быть critical"


def test_local_cause():
    clean = _flat()
    clim = build_climatology(clean)
    df = clean.copy()
    truth = _dip(df, "T-01", "2023-08-01", "2023-08-08", -0.18, -0.14)
    scored, events = detect_anomalies(df, clim)
    mine = [e for e in events if e["polygon_id"] == "T-01" and _overlap(e, truth) >= 2]
    assert mine
    exp = explain_event(mine[0], scored.rename(columns={TARGET_COL: "primary_ndvi"}))
    assert "локальн" in exp["likely_cause"].lower()
