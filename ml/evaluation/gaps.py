"""Synthetic gap training (§11) и таблица по длинам пропусков (§12).

Из известных значений primary_ndvi вырезаем искусственные пропуски,
предсказываем их и сравниваем с оригиналом — так измеряется RMSE честно,
без доступа к скрытому тесту.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ml.data.contract import TARGET_COL

GAP_LENGTHS = [1, 3, 7, 14, 30]


def mask_random_gaps(
    df: pd.DataFrame,
    gap_len: int = 7,
    n_gaps: int = 5,
    seed: int = 42,
) -> pd.DataFrame:
    """Копирует df и маскирует сегменты target как NaN с флагом is_synthetic_gap."""
    rng = np.random.default_rng(seed)
    out = df.copy().sort_values(["polygon_id", "date"]).reset_index(drop=True)
    out["is_synthetic_gap"] = False
    for pid, idx in out.groupby("polygon_id").groups.items():
        locs = list(idx)
        valid = [i for i in locs if pd.notna(out.at[i, TARGET_COL])]
        for _ in range(n_gaps):
            if len(valid) < gap_len:
                break
            start = int(rng.integers(0, len(valid) - gap_len + 1))
            seg = valid[start : start + gap_len]
            # маскируем только если весь сегмент был известен
            if all(pd.notna(out.at[i, TARGET_COL]) for i in seg):
                out.loc[seg, TARGET_COL] = np.nan
                out.loc[seg, "is_synthetic_gap"] = True
    return out


def gap_report_table(results: dict[str, dict[int, float]]) -> pd.DataFrame:
    """Строит таблицу §12: строки — методы, колонки — длины пропусков."""
    return pd.DataFrame(results).T[["1d", "3d", "7d", "14d", "30d"]] if results else pd.DataFrame()
