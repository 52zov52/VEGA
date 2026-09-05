"""Финальная линейка: production-артефакты на большом фиксированном пуле 1d-масок.

Один запуск, без подбора — только честный замер того, что уедет в сабмишен.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ml.data.contract import TARGET_COL, normalize_columns
from ml.evaluation.gaps import mask_random_gaps
from ml.evaluation.metrics import gap_score, rmse
from ml.evaluation.splits import time_forward_splits
from ml.inference.predict import load_artifacts, predict_gaps
from ml.models.baselines import baseline_linear
from services.climatology.climatology import PastClimatology

SEEDS = [101, 102, 103, 104, 105, 106, 107, 108]
# Плотность как в скрытом тесте: 3112/57185 ≈ 5.4% строк.
# n_gaps в mask_random_gaps — на полигон: 5*39/2848 ≈ 7%.


def main():
    df = normalize_columns(pd.read_csv(ROOT / "data" / "train_dataset.csv"))
    df = df[df[TARGET_COL].notna()].copy()
    _, valid_df = time_forward_splits(df)[-1]
    art = load_artifacts(ROOT / "models")
    assert art is not None, "нет артефактов"
    clim = PastClimatology().fit(df[pd.to_datetime(df["date"]) < "2024-01-01"])
    Y, P, L = [], [], []
    for s in SEEDS:
        masked = mask_random_gaps(valid_df, gap_len=1, n_gaps=5, seed=s)
        sel = masked["is_synthetic_gap"].to_numpy()
        key = masked[sel].set_index(["polygon_id", "date"]).index
        y = valid_df.set_index(["polygon_id", "date"])[TARGET_COL].loc[key].to_numpy(float)
        p = predict_gaps(masked, art, clim=clim).to_numpy(float)[sel]
        lin = []
        for _, sub in masked.groupby("polygon_id"):
            ss = sub.set_index("date")[TARGET_COL].astype(float)
            lin += baseline_linear(ss).loc[sub.set_index("date").index[sub["is_synthetic_gap"].to_numpy()]].tolist()
        Y.append(y); P.append(p); L.append(np.asarray(lin, float))
    y, p, lin = np.concatenate(Y), np.concatenate(P), np.concatenate(L)
    r, rl = rmse(y, p), rmse(y, lin)
    print(f"FINAL-RULER 1d pooled n={len(y)}: model={r:.4f} (score {gap_score(r)}) | linear={rl:.4f} (score {gap_score(rl)})")


if __name__ == "__main__":
    main()
