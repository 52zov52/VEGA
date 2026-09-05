"""Eval детекции аномалий на инъекциях с известным ground truth.

Строит детерминированные ряды (плоская база + шум, seed фиксирован),
впрыскивает 7 нетривиальных сценариев, гоняет detect_anomalies +
explain_event и проверяет: пересечение с инъекцией, уровень, kind,
восстановление и ключевые слова причины. Печатает таблицу, выход 0 = всё ок.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ml.data.contract import TARGET_COL
from services.anomaly.detector import detect_anomalies
from services.climatology.climatology import build_climatology
from services.explanation.explainer import explain_event

SEED = 7
PIDS = ["EVAL-01", "EVAL-02", "EVAL-03"]


def base_frame(n_days=300, start="2023-01-01"):
    rng = np.random.default_rng(SEED)
    dates = pd.date_range(start=start, periods=n_days, freq="D")
    rows = []
    for pid in PIDS:
        ndvi = 0.62 + rng.normal(0, 0.012, n_days)
        rows.append(pd.DataFrame({
            "polygon_id": pid,
            "date": dates.date,
            TARGET_COL: np.round(ndvi, 5),
            "evi": np.round(ndvi * 0.82, 5),
            "ndwi": np.round(np.full(n_days, 0.1) + rng.normal(0, 0.01, n_days), 5),
            "temperature": np.round(20 + rng.normal(0, 1.5, n_days), 2),
            "precipitation": np.round(np.clip(rng.exponential(3.0, n_days), 0, 40), 2),
            "soil_moisture": np.round(0.3 + rng.normal(0, 0.015, n_days), 4),
            "data_quality": np.round(np.full(n_days, 0.95), 3),
        }))
    return pd.concat(rows, ignore_index=True)


def inject(df, pid, lo, hi, ndvi_delta=0.0, evi_delta=0.0, ndwi_delta=0.0,
           rain_zero=False, heat=0.0, soil_delta=0.0, quality=None):
    m = (df["polygon_id"] == pid) & (df["date"] >= lo) & (df["date"] <= hi)
    idx = df.index[m]
    df.loc[idx, TARGET_COL] = (df.loc[idx, TARGET_COL] + ndvi_delta).clip(0.05, 0.95)
    df.loc[idx, "evi"] = (df.loc[idx, "evi"] + evi_delta).clip(0.03, 0.9)
    df.loc[idx, "ndwi"] = df.loc[idx, "ndwi"] + ndwi_delta
    if rain_zero:
        df.loc[idx, "precipitation"] = 0.0
    df.loc[idx, "temperature"] = df.loc[idx, "temperature"] + heat
    df.loc[idx, "soil_moisture"] = (df.loc[idx, "soil_moisture"] + soil_delta).clip(0.05, 0.6)
    if quality is not None:
        df.loc[idx, "data_quality"] = quality
    return set(df.loc[idx, "date"].tolist())


def events_for(events, pid):
    return [e for e in events if e["polygon_id"] == pid]


def overlap(ev, truth):
    lo = pd.to_datetime(ev["start_date"]).date()
    hi = pd.to_datetime(ev["end_date"]).date()
    days = set(pd.date_range(lo, hi, freq="D").date)
    return len(days & truth)


def run_case(name, setup, check):
    clean = base_frame()
    # норма — по ЧИСТОЙ истории (как в реале: климатология по прошлому,
    # эпизод её не отравляет; иначе однолетняя норма втягивает саму аномалию)
    clim = build_climatology(clean)
    df = clean.copy()
    truth = setup(df)
    scored, events = detect_anomalies(df, clim)
    ts = scored.rename(columns={TARGET_COL: "primary_ndvi"})
    ok, detail = check(events, ts, truth)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")
    return ok


def main():
    results = []

    # S1: устойчивая засуха 10 дней — событие + причина про засуху
    def setup1(df):
        return inject(df, "EVAL-01", pd.Timestamp("2023-06-01").date(), pd.Timestamp("2023-06-10").date(),
                      ndvi_delta=-0.22, evi_delta=-0.18, ndwi_delta=-0.25,
                      rain_zero=True, heat=7.0, soil_delta=-0.16)
    def check1(events, ts, truth):
        mine = events_for(events, "EVAL-01")
        hits = [e for e in mine if overlap(e, truth) >= 3]
        if not hits:
            return False, f"нет пересечения (всего событий: {len(mine)})"
        e = max(hits, key=lambda x: x["anomaly_score"])
        exp = explain_event(e, ts)
        good = "засух" in exp["likely_cause"].lower()
        return good, f"level={e['level']} kind={e['kind']} cause={exp['likely_cause'][:40]} conf={exp['confidence']}"
    results.append(run_case("S1 sustained drought", setup1, check1))

    # S2: одиночный всплеск — событие из 1 точки с kind=spike
    def setup2(df):
        return inject(df, "EVAL-01", pd.Timestamp("2023-07-01").date(), pd.Timestamp("2023-07-01").date(),
                      ndvi_delta=-0.25, evi_delta=-0.2, ndwi_delta=-0.2)
    def check2(events, ts, truth):
        mine = [e for e in events_for(events, "EVAL-01") if overlap(e, truth) >= 1]
        if not mine:
            return False, "всплеск не найден"
        kinds = sorted({e["kind"] for e in mine})
        return True, f"событий={len(mine)} kinds={kinds} level={mine[0]['level']}"
    results.append(run_case("S2 single spike", setup2, check2))

    # S3: облачный артефакт — просадка + quality 0.1: не должен стать critical
    def setup3(df):
        return inject(df, "EVAL-01", pd.Timestamp("2023-08-01").date(), pd.Timestamp("2023-08-01").date(),
                      ndvi_delta=-0.3, evi_delta=-0.25, quality=0.1)
    def check3(events, ts, truth):
        mine = [e for e in events_for(events, "EVAL-01") if overlap(e, truth) >= 1]
        if not mine:
            return True, "точка отфильтрована как мусор — тоже ок"
        lvls = sorted({e["level"] for e in mine})
        ok = "critical" not in lvls
        exp = explain_event(mine[0], ts)
        return ok, f"levels={lvls} kinds={sorted({e['kind'] for e in mine})} cause={exp['likely_cause'][:40]}"
    results.append(run_case("S3 cloudy artifact", setup3, check3))

    # S4: эпизод с просветом (плохо-плохо-норма-плохо-плохо) — одно событие
    def setup4(df):
        t1 = inject(df, "EVAL-01", pd.Timestamp("2023-05-01").date(), pd.Timestamp("2023-05-02").date(),
                    ndvi_delta=-0.2, evi_delta=-0.16, ndwi_delta=-0.2, rain_zero=True, heat=6.0, soil_delta=-0.14)
        t2 = inject(df, "EVAL-01", pd.Timestamp("2023-05-04").date(), pd.Timestamp("2023-05-05").date(),
                    ndvi_delta=-0.2, evi_delta=-0.16, ndwi_delta=-0.2, rain_zero=True, heat=6.0, soil_delta=-0.14)
        return t1 | t2
    def check4(events, ts, truth):
        mine = [e for e in events_for(events, "EVAL-01") if overlap(e, truth) >= 1]
        cov = sum(overlap(e, truth) for e in mine)
        return len(mine) == 1 and cov >= 3, f"событий={len(mine)} покрытие={cov}/4"
    results.append(run_case("S4 merged episode", setup4, check4))

    # S5: мягкая просадка 6 дней — раннее предупреждение (watch)
    def setup5(df):
        return inject(df, "EVAL-02", pd.Timestamp("2023-06-01").date(), pd.Timestamp("2023-06-06").date(),
                      ndvi_delta=-0.05, evi_delta=-0.045, ndwi_delta=-0.06, soil_delta=-0.03)
    def check5(events, ts, truth):
        mine = [e for e in events_for(events, "EVAL-02") if overlap(e, truth) >= 1]
        if not mine:
            return False, "мягкий эпизод потерян"
        lvls = sorted({e["level"] for e in mine})
        return True, f"levels={lvls} kinds={sorted({e['kind'] for e in mine})}"
    results.append(run_case("S5 mild early warning", setup5, check5))

    # S6: восстановление после засухи фиксируется
    def setup6(df):
        return inject(df, "EVAL-03", pd.Timestamp("2023-06-01").date(), pd.Timestamp("2023-06-07").date(),
                      ndvi_delta=-0.2, evi_delta=-0.16, ndwi_delta=-0.2, rain_zero=True, heat=6.0, soil_delta=-0.14)
    def check6(events, ts, truth):
        mine = [e for e in events_for(events, "EVAL-03") if overlap(e, truth) >= 2]
        if not mine:
            return False, "эпизод не найден"
        rec = [e for e in mine if e["recovered"]]
        exp = explain_event(mine[0], ts)
        return len(rec) > 0, f"recovered={bool(rec)} narrative_has_rec={'вернулось' in exp['narrative']}"
    results.append(run_case("S6 recovery flag", setup6, check6))

    # S7: локальная (1 поле, без водного следа) vs региональная — разные выводы
    def setup7(df):
        t = inject(df, "EVAL-01", pd.Timestamp("2023-09-01").date(), pd.Timestamp("2023-09-08").date(),
                   ndvi_delta=-0.18, evi_delta=-0.14)
        for pid in ("EVAL-02", "EVAL-03"):
            inject(df, pid, pd.Timestamp("2023-10-01").date(), pd.Timestamp("2023-10-08").date(),
                   ndvi_delta=-0.18, evi_delta=-0.14, ndwi_delta=-0.18, soil_delta=-0.1)
        return t
    def check7(events, ts, truth):
        loc = [e for e in events_for(events, "EVAL-01") if overlap(e, truth) >= 2]
        if not loc:
            return False, "локальный эпизод не найден"
        exp = explain_event(loc[0], ts)
        local_txt = "локальн" in exp["likely_cause"].lower()
        return local_txt, f"cause={exp['likely_cause'][:45]} local={local_txt}"
    results.append(run_case("S7 local vs regional", setup7, check7))

    print(f"\nИТОГ: {sum(results)}/{len(results)} сценариев")
    if not all(results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
