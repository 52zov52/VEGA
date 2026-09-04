"""Климатологическая норма NDVI_climatology(doy) (§14).

Ожидаемое значение NDVI для конкретной фазы сезона по истории полигона:
mean/std по дню года в окне ±7 дней со сглаживанием. Anomaly и Z считаются
от этой нормы; это же база seasonal baseline и Z-score детектора.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ml.data.contract import TARGET_COL


def build_climatology(df: pd.DataFrame, window: int = 7) -> pd.DataFrame:
    work = df.copy()
    work["_d"] = pd.to_datetime(work["date"])
    work["_doy"] = work["_d"].dt.dayofyear
    rows: list[dict] = []
    for (pid, doy), _ in work.groupby(["polygon_id", "_doy"]):
        vals: list[float] = []
        for d in range(int(doy) - window, int(doy) + window + 1):
            dd = ((d - 1) % 366) + 1
            vals += work[(work["polygon_id"] == pid) & (work["_doy"] == dd)][TARGET_COL].dropna().tolist()
        if vals:
            rows.append({"polygon_id": pid, "doy": int(doy),
                         "clim_mean": float(np.mean(vals)),
                         "clim_std": float(max(np.std(vals), 0.02)),
                         "clim_n": int(len(vals))})
    clim = pd.DataFrame(rows)
    if len(clim):
        # лёгкое сглаживание по дню года внутри полигона
        clim = clim.sort_values(["polygon_id", "doy"])
        clim["clim_mean"] = clim.groupby("polygon_id")["clim_mean"].transform(
            lambda s: s.rolling(15, center=True, min_periods=1).mean())
    return clim


def attach_climatology(df: pd.DataFrame, clim: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()
    work["_d"] = pd.to_datetime(work["date"])
    work["_doy"] = work["_d"].dt.dayofyear
    out = work.merge(clim, left_on=["polygon_id", "_doy"], right_on=["polygon_id", "doy"], how="left")
    global_mean = float(work[TARGET_COL].median()) if TARGET_COL in work and work[TARGET_COL].notna().any() else 0.5
    out["clim_mean"] = out["clim_mean"].fillna(global_mean)
    out["clim_std"] = out["clim_std"].fillna(0.05)
    out["zscore"] = (out[TARGET_COL] - out["clim_mean"]) / out["clim_std"].clip(lower=0.02)
    return out.drop(columns=[c for c in ("_d", "_doy", "doy", "clim_n") if c in out.columns])


class PastClimatology:
    """Строго past-only климатология для ML-признаков (§30).

    fit(df) запоминает известные значения по (полигон, год, doy).
    transform(df) для каждой строки считает mean/std по окну doy ± window
    только за годы СТРОГО раньше года строки. Будущие значения, включая
    текущий год, не используются — это проверяется тестом.
    """

    def __init__(self, window: int = 7):
        self.window = window
        self._poly: dict[str, dict] = {}
        self.global_mean: float = 0.5
        self.global_std: float = 0.05

    def fit(self, df: pd.DataFrame) -> "PastClimatology":
        work = df.copy()
        work["_d"] = pd.to_datetime(work["date"])
        work["_year"] = work["_d"].dt.year
        work["_doy"] = work["_d"].dt.dayofyear
        known = work[work[TARGET_COL].notna()]
        if len(known):
            self.global_mean = float(known[TARGET_COL].mean())
            self.global_std = float(max(known[TARGET_COL].std(), 0.02))
        for pid, sub in known.groupby("polygon_id"):
            years = sorted(sub["_year"].unique().tolist())
            yidx = {y: i for i, y in enumerate(years)}
            sums = np.zeros((len(years), 367))
            sq = np.zeros((len(years), 367))
            cnt = np.zeros((len(years), 367))
            for y, d, v in zip(sub["_year"].to_numpy(), sub["_doy"].to_numpy(), sub[TARGET_COL].to_numpy(float)):
                d = min(max(int(d), 1), 366)
                sums[yidx[y], d] += v
                sq[yidx[y], d] += v * v
                cnt[yidx[y], d] += 1
            self._poly[str(pid)] = {
                "years": years,
                "psum": np.vstack([np.zeros(367), np.cumsum(sums, axis=0)]),
                "qsum": np.vstack([np.zeros(367), np.cumsum(sq, axis=0)]),
                "csum": np.vstack([np.zeros(367), np.cumsum(cnt, axis=0)]),
                "mean": float(sub[TARGET_COL].mean()),
            }
        return self

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        work = df.copy()
        work["_d"] = pd.to_datetime(work["date"])
        work["_year"] = work["_d"].dt.year
        work["_doy"] = work["_d"].dt.dayofyear
        means = np.full(len(work), np.nan)
        stds = np.full(len(work), np.nan)
        w = self.window
        for (pid, year), idx in work.groupby(["polygon_id", "_year"]).groups.items():
            info = self._poly.get(str(pid))
            pos = np.asarray(list(idx))
            doys = work.loc[pos, "_doy"].to_numpy(int)
            if info is None:
                means[pos] = self.global_mean
                stds[pos] = self.global_std
                continue
            import bisect

            k = bisect.bisect_left(info["years"], int(year))  # годы строго раньше
            if k == 0:
                means[pos] = info["mean"]
                stds[pos] = self.global_std
                continue
            # циркулярный паддинг по doy для окна ±w
            ps, qs, cs = info["psum"][k], info["qsum"][k], info["csum"][k]
            ext_s = np.concatenate([ps[366 - w:], ps[1:], ps[1:1 + w]])
            ext_q = np.concatenate([qs[366 - w:], qs[1:], qs[1:1 + w]])
            ext_c = np.concatenate([cs[366 - w:], cs[1:], cs[1:1 + w]])
            ker_s = np.cumsum(np.concatenate([[0.0], ext_s]))
            ker_q = np.cumsum(np.concatenate([[0.0], ext_q]))
            ker_c = np.cumsum(np.concatenate([[0.0], ext_c]))
            for j, p in enumerate(pos):
                d = min(max(int(doys[j]), 1), 366)
                s = d + w  # центр doy d в extended-массиве (w+1_pad + d-1)
                s_sum = ker_s[s + w + 1] - ker_s[s - w]
                q_sum = ker_q[s + w + 1] - ker_q[s - w]
                c_sum = ker_c[s + w + 1] - ker_c[s - w]
                if c_sum > 0:
                    m = s_sum / c_sum
                    means[p] = m
                    stds[p] = max(float(np.sqrt(max(q_sum / c_sum - m * m, 0.0))), 0.02)
                else:
                    means[p] = info["mean"]
                    stds[p] = self.global_std
        work["past_clim_mean"] = pd.Series(means, index=work.index).fillna(self.global_mean).to_numpy()
        work["past_clim_std"] = pd.Series(stds, index=work.index).fillna(self.global_std).to_numpy()
        return work.drop(columns=["_d", "_year", "_doy"])
