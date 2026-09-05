"""Multi-signal детектор аномалий (§15-16) поверх Z-score (§14).

Веса конфигурируются через .env. Пороги уровней откалиброваны по разметке
организаторов (train status, corr нашего z с ndvi_zscore = 0.975):
critical редкий и точный, stress — точный, watch — чувствительный ранний
сигнал. Пороги переопределяются через ANOMALY_Z_*/ANOMALY_S_*.
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd

from ml.data.contract import TARGET_COL


def _w(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


# Пороги уровней: сначала z (отклонение от нормы), затем score (согласие
# сигналов) — пара условий режет одиночные шумовые пики.
LVL = {
    "critical": (_w("ANOMALY_Z_CRITICAL", -2.0), _w("ANOMALY_S_CRITICAL", 0.50)),
    "stress": (_w("ANOMALY_Z_STRESS", -1.2), _w("ANOMALY_S_STRESS", 0.30)),
    "watch": (_w("ANOMALY_Z_WATCH", -0.8), _w("ANOMALY_S_WATCH", 0.15)),
}


def detect_anomalies(df: pd.DataFrame, clim: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    from services.climatology.climatology import attach_climatology

    w_ndvi = _w("ANOMALY_W_NDVI", 0.35)
    w_evi = _w("ANOMALY_W_EVI", 0.15)
    w_ndwi = _w("ANOMALY_W_NDWI", 0.15)
    w_wx = _w("ANOMALY_W_WEATHER", 0.15)
    w_soil = _w("ANOMALY_W_SOIL", 0.10)
    w_trend = _w("ANOMALY_W_TREND", 0.10)

    work = attach_climatology(df, clim).sort_values(["polygon_id", "date"]).copy()
    # нормированные сигналы 0..1 (сила негативного отклонения)
    work["sig_ndvi"] = (-work["zscore"]).clip(lower=0, upper=4) / 4
    for col, sig in (("evi", "sig_evi"), ("ndwi", "sig_ndwi")):
        if col in work.columns:
            m = work.groupby("polygon_id")[col].transform("mean")
            s = work.groupby("polygon_id")[col].transform("std").fillna(0.05).clip(lower=0.02)
            work[sig] = ((m - work[col]) / s).clip(lower=0, upper=4) / 4
        else:
            work[sig] = 0.0
    # погодный стресс: жара + дефицит осадков относительно среднего полигона
    if "temperature" in work.columns:
        tm = work.groupby("polygon_id")["temperature"].transform("mean")
        work["sig_heat"] = ((work["temperature"] - tm) / 5.0).clip(lower=0, upper=3) / 3
    else:
        work["sig_heat"] = 0.0
    if "precipitation" in work.columns:
        # скользящая сумма осадков 30 дней vs средняя
        pr = work.groupby("polygon_id")["precipitation"].transform(lambda s: s.fillna(0).rolling(4, min_periods=1).sum())
        prm = pr.mean()
        work["sig_dry"] = ((prm - pr) / max(prm, 1.0)).clip(lower=0, upper=1)
    else:
        work["sig_dry"] = 0.0
    work["sig_weather"] = (work["sig_heat"] + work["sig_dry"]) / 2
    if "soil_moisture" in work.columns:
        sm = work.groupby("polygon_id")["soil_moisture"].transform("mean")
        work["sig_soil"] = ((sm - work["soil_moisture"]) / 0.15).clip(lower=0, upper=2) / 2
    else:
        work["sig_soil"] = 0.0
    # тренд: скорость падения NDVI за 2 шага
    work["ndvi_slope"] = work.groupby("polygon_id")[TARGET_COL].transform(lambda s: s.diff(2) / 2)
    work["sig_trend"] = ((-work["ndvi_slope"]) / 0.05).clip(lower=0, upper=2) / 2

    # доверие точке пропорционально качеству данных: облачный пиксель не должен
    # давать critical. Погода/почва/тренд — контекстные, их не трогаем.
    if "data_quality" in work.columns:
        q = pd.to_numeric(work["data_quality"], errors="coerce").fillna(1.0).clip(0, 1)
        qf = ((q - 0.2) / 0.6).clip(lower=0.15, upper=1.0)
        for sig in ("sig_ndvi", "sig_evi", "sig_ndwi"):
            work[sig] = work[sig] * qf

    work["anomaly_score"] = (
        w_ndvi * work["sig_ndvi"] + w_evi * work["sig_evi"] + w_ndwi * work["sig_ndwi"]
        + w_wx * work["sig_weather"] + w_soil * work["sig_soil"] + w_trend * work["sig_trend"]
    ).clip(0, 1)

    def level(row) -> str:
        # комбинируем z и score, чтобы не срабатывать на одиночный шумовой пик;
        # пороги — из LVL (калибровка по разметке организаторов)
        z, s = row["zscore"], row["anomaly_score"]
        if z < LVL["critical"][0] and s > LVL["critical"][1]:
            return "critical"
        if z < LVL["stress"][0] and s > LVL["stress"][1]:
            return "stress"
        if z < LVL["watch"][0] and s > LVL["watch"][1]:
            return "watch"
        return "normal"

    work["level"] = work.apply(level, axis=1)
    work["deviation_pct"] = ((work[TARGET_COL] - work["clim_mean"]) / work["clim_mean"].clip(lower=0.05) * 100).fillna(0)

    # группируем последовательные stress/critical в события.
    # Нетривиальные случаи (критерий «Детекция аномалий»):
    #  - watch включается как early_warning (иначе ранние сигналы теряются);
    #  - короткие нормальные просветы (<= MERGE_GAP) внутри плохого периода
    #    не рвут эпизод (облачный пропуск/шум не должны дробить засуху);
    #  - одиночный плохой шаг с ужасным качеством данных понижается до watch
    #    (защита от ложных critical по облакам);
    #  - одиночные всплески помечаются kind=spike, устойчивые — sustained,
    #    среднее качество < 0.4 — kind=uncertain;
    #  - фиксируем восстановление (возврат к норме сразу после эпизода).
    max_merge_gap = _w("VEGA_MERGE_GAP", 2)
    watch_as_event = os.getenv("VEGA_WATCH_EVENTS", "1") == "1"

    def status_of(level: str) -> int:
        if level in ("stress", "critical"):
            return 2
        if level == "watch" and watch_as_event:
            return 1
        return 0

    work["_status"] = work["level"].map(status_of)
    quality = work["data_quality"] if "data_quality" in work else pd.Series(1.0, index=work.index)

    events: list[dict] = []
    for pid, sub in work.sort_values("date").groupby("polygon_id"):
        # quality в позициях sub ДО reset_index (индексы work), дальше — позиционно
        qsub = pd.to_numeric(quality.loc[sub.index], errors="coerce").fillna(1.0).to_numpy(dtype=float)
        sub = sub.reset_index(drop=True)
        n = len(sub)
        i = 0
        while i < n:
            if sub.loc[i, "_status"] == 0:
                i += 1
                continue
            # начало сегмента; тянем, допуская короткие просветы
            start = i
            gap = 0
            last = i
            j = i
            has_bad = False
            while j < n:
                st = sub.loc[j, "_status"]
                if st >= 1:
                    gap = 0
                    last = j
                    if st == 2:
                        has_bad = True
                else:
                    gap += 1
                    # просвет допустим только внутри уже-плохого эпизода
                    if not has_bad or gap > max_merge_gap:
                        break
                j += 1
            end = last + 1  # отрезаем висячий просвет
            seg = sub.iloc[start:end]
            if len(seg) == 0:
                i = j
                continue
            worst = seg.loc[seg["anomaly_score"].idxmax()]
            seg_scores = seg["anomaly_score"].to_numpy(dtype=float)
            worst_s = float(np.nanmax(seg_scores))
            rest = seg_scores[~np.isclose(seg_scores, worst_s)] if len(seg_scores) > 1 else np.array([])
            rest_max = float(np.nanmax(rest)) if len(rest) else 0.0
            # выраженный пик на коротком эпизоде — тоже всплеск, даже если шумные
            # соседи дотянули до watch и приклеились при склейке
            prominent = len(seg) <= 3 and worst_s >= 1.8 * max(rest_max, 0.1)
            seg_q = float(qsub[start:end].mean()) if end > start else 1.0
            seg_level: str = "watch"
            if (seg["level"] == "critical").any():
                seg_level = "critical"
            elif (seg["level"] == "stress").any():
                seg_level = "stress"
            # одиночный плохой шаг на мусоре (облака) — не critical/stress
            if len(seg) == 1 and seg_level in ("stress", "critical"):
                q0 = float(qsub[start])
                if q0 < 0.3 and float(worst["anomaly_score"]) < 0.7:
                    seg_level = "watch"
            if seg_level == "watch":
                kind = "uncertain" if seg_q < 0.4 else ("spike" if (len(seg) == 1 or prominent) else "early_warning")
            else:
                kind = "uncertain" if seg_q < 0.4 else ("spike" if (len(seg) == 1 or prominent) else "sustained")
            # восстановление: первые шаги после эпизода снова в норме
            recovered, recovery_date = False, None
            look = sub.iloc[end:end + 4]
            if len(look) and (look["level"] == "normal").all():
                recovered = True
                recovery_date = str(look["date"].iloc[0])
            events.append({
                "polygon_id": pid,
                "start_date": str(seg["date"].iloc[0]),
                "end_date": str(seg["date"].iloc[-1]),
                "level": seg_level,
                "kind": kind,
                "anomaly_score": round(float(worst["anomaly_score"]), 3),
                "zscore": round(float(worst["zscore"]), 2),
                "deviation_pct": round(float(worst["deviation_pct"]), 1),
                "duration_steps": int(len(seg)),
                "data_quality": round(seg_q, 3),
                "recovered": recovered,
                "recovery_date": recovery_date,
            })
            i = max(end, start + 1)
    # соседнее отклонение: флаг локальной проблемы (§18 сценарий 2).
    # Считаем строго по ДРУГИМ полигонам, иначе свой же провал тянет среднее
    # (критично при малом числе полигонов, в проде разница мала).
    if events:
        work["_d"] = pd.to_datetime(work["date"]).dt.date
        for e in events:
            day = pd.to_datetime(e["start_date"]).date()
            others = work[(work["_d"] == day) & (work["polygon_id"] != e["polygon_id"])]["deviation_pct"]
            e["neighbour_deviation"] = round(float(others.mean()) if len(others) else 0.0, 1)
        work.drop(columns=["_d"], inplace=True, errors="ignore")
    return work, events
