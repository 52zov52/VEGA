"""Inference без утечек (§28-30): восстановление пропусков обученным ансамблем.

Алгоритм: seasonal/linear преднаполнение для лагов -> GBM + Temporal
предсказания на пропущенных позициях -> взвешенный ансамбль. Известные
значения никогда не перезаписываются. Сохраняемые артефакты: gbm.joblib,
temporal.joblib, seasonal parquet климатологии, meta.json.
"""
from __future__ import annotations

from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from ml.data.contract import TARGET_COL
from ml.features.build import build_features
from ml.models.baselines import baseline_linear, baseline_seasonal
from ml.models.ensemble import EnsembleWeights, ensemble_predict


def load_artifacts(model_dir: str | Path) -> dict | None:
    model_dir = Path(model_dir)
    gbm_p = model_dir / "gbm.joblib"
    tmp_p = model_dir / "temporal.joblib"
    if not gbm_p.exists() or not tmp_p.exists():
        return None
    import json

    bundle = {"gbm": joblib.load(gbm_p), "temporal": joblib.load(tmp_p)}
    meta_p = model_dir / "meta.json"
    if meta_p.exists():
        meta = json.loads(meta_p.read_text(encoding="utf-8"))
        bundle["weights"] = EnsembleWeights(**meta.get("weights", {}))
        bundle["feature_cols"] = meta.get("feature_cols", [])
    else:
        bundle["weights"] = EnsembleWeights()
        bundle["feature_cols"] = []
    return bundle


def predict_gaps(df: pd.DataFrame, artifacts: dict) -> pd.Series:
    """Возвращает Series восстановленного target в порядке входного df."""
    work = df.copy()
    work["date"] = pd.to_datetime(work["date"]).dt.date
    order = work.index
    mask = work[TARGET_COL].isna()
    if not mask.any():
        return work[TARGET_COL].astype(float)
    # Преднаполнение прошлым: линейная интерполяция для стабильных лагов.
    prefilled = work.copy()
    prefilled[TARGET_COL] = prefilled.groupby("polygon_id")[TARGET_COL].transform(baseline_linear)
    feat, cols = build_features(prefilled)
    feat_cols = artifacts.get("feature_cols") or cols
    feat_cols = [c for c in feat_cols if c in feat.columns]
    X = feat[feat_cols]
    p_gbm = np.asarray(artifacts["gbm"].predict(X), dtype=float)
    p_tmp = np.asarray(artifacts["temporal"].predict(feat), dtype=float)
    p_sea = baseline_seasonal(prefilled).to_numpy(dtype=float)
    ens = ensemble_predict(p_gbm, p_tmp, p_sea, artifacts.get("weights"))
    out = work[TARGET_COL].astype(float)
    out.loc[mask] = pd.Series(ens, index=work.index).loc[mask]
    return out.loc[order].clip(0, 1)
