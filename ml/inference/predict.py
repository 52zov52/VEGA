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
from ml.models.baselines import baseline_seasonal
from ml.models.ensemble import EnsembleWeights, apply_stratified, ensemble_predict


def load_artifacts(model_dir: str | Path) -> dict | None:
    """Загрузка артефактов модели для инференса.

    Загружает сохраненные модели и метаданные из директории модели.

    Args:
        model_dir: путь к директории с артефактами модели

    Returns:
        словарь с загруженными Artefактами или None, если модели не найдены:
        - gbm: обученная модель GBM
        - temporal: обученная temporal модель
        - weights: веса ансамбля (EnsembleWeights)
        - feature_cols: список используемых признаков
        - weights_by_bin: веса, стратифицированные по DSO (days since observation)
        - gap_weights_per_len: per-gap-length weights (новое поле)
    """
    model_dir = Path(model_dir)
    gbm_p = model_dir / "gbm.joblib"
    tmp_p = model_dir / "temporal.joblib"
    if not gbm_p.exists() or not tmp_p.exists():
        return None  # Модели не обучались, артефакты отсутствуют

    import json

    bundle = {"gbm": joblib.load(gbm_p), "temporal": joblib.load(tmp_p)}
    meta_p = model_dir / "meta.json"
    if meta_p.exists():
        meta = json.loads(meta_p.read_text(encoding="utf-8"))
        # Загружаем базовые веса ансамбля из метаданных
        bundle["weights"] = EnsembleWeights(**meta.get("weights", {}))
        # Список имен признаков, использованных при обучении
        bundle["feature_cols"] = meta.get("feature_cols", [])
        # Загружаем веса, стратифицированные по бинам DSO (days since observation)
        raw_bins = meta.get("weights_by_bin") or {}
        bundle["weights_by_bin"] = {k: EnsembleWeights(**v) for k, v in raw_bins.items()}
        # НОВОЕ: Per-gap-length weights, сохраненые при обучении
        bundle["gap_weights_per_len"] = meta.get("gap_weights_per_len", {})
    else:
        # Если метафайла нет, инициализируем пустые значения
        bundle["weights"] = EnsembleWeights()
        bundle["weights_by_bin"] = {}
        bundle["feature_cols"] = []
        bundle["gap_weights_per_len"] = {}
    return bundle


def predict_gaps(df: pd.DataFrame, artifacts: dict, clim=None, gap_lens: np.ndarray | None = None) -> pd.Series:
    """Возвращает Series восстановленного target (primary_ndvi) в порядке входного df.

    Алгоритм инференса:
    1. Копируем входной датафрейм и подготовка дат
    2. Находим маску пропусков в target колонке
    3. Если пропусков нет — возвращаем float версию target
    4. Фит PastClimatology (климатология) на известных данных (только train-история)
    5. Строим фичи через build_features (включает лаги, сезонность и т.д.)
    6. Получаем предсказания от GBM модели
    7. Получаем предсказания от temporal (MLP) модели
    8. Получаем seasonalную baseline (база по климатологии)
    9. Стратифицированное взвешивание ансамбля по DSO (days since observation)
    10. Заполняем пропуски предсказаниями, известные значения не перезаписываются

    Args:
        df: входной датафрейм с данными (must have TARGET_COL column)
        artifacts: загруженные артефакты от load_artifacts()
        clim: fitted PastClimatology объект. Если None — фит на данных входного df.
        gap_lens: массив длин gaps для каждой строки (опционально).
            Нужно для per-gap-length стратегии взвешивания ансамбля.

    Returns:
        Series восстановленных значений primary_ndvi в порядке входного df.
        Результат клипится в диапазон [0, 1], так как NDVI всегда в этом диапазоне.

    Примечание: known (известные) значения never перезаписываются.
    """
    from services.climatology.climatology import PastClimatology

    work = df.copy()
    work["date"] = pd.to_datetime(work["date"]).dt.date
    order = work.index
    mask = work[TARGET_COL].isna()
    if not mask.any():
        # Если пропусков нет, просто возвращаем float версию target
        return work[TARGET_COL].astype(float)

    # Past-only климатология по истинно известным (NaN пропусков не участвуют).
    # Фит климатологии только на известных значениях, чтобы избежать утечек данных.
    if clim is None:
        clim = PastClimatology().fit(work)

    # build_features сам предзаполняет ряд для лагов; sparsity/spatial
    # считаются по сырым NaN, поэтому сюда передаём work как есть.
    feat, cols = build_features(work, clim=clim)
    feat_cols = artifacts.get("feature_cols") or cols
    # Оставляем только те колонки, которые есть в фичах
    feat_cols = [c for c in feat_cols if c in feat.columns]
    X = feat[feat_cols]
    # Предсказание от GBM модели (Tree-based модель)
    p_gbm = np.asarray(artifacts["gbm"].predict(X), dtype=float)
    # Предсказание от temporal (MLP/Neural Network) модели
    p_tmp = np.asarray(artifacts["temporal"].predict(feat), dtype=float)
    # Seasonalная baseline (база по климатической норме)
    p_sea = baseline_seasonal(work).to_numpy(dtype=float)
    # Стратификация по давности наблюдения (past-only признак, без утечек):
    # days_since_obs показывает, сколько дней прошло с последнего наблюдения.
    # Свежим наблюдениям важнее GBM/interpolation, далёким — Seasonal.
    # Порядок feat совпадает с порядок ens, как и раньше для work.index.
    dso = feat["days_since_obs"].to_numpy() if "days_since_obs" in feat else None
    # Применяем стратифицированное взвешивание ансамбля
    ens = apply_stratified(p_gbm, p_tmp, p_sea, dso,
                           artifacts.get("weights_by_bin"), artifacts.get("weights"))
    # Формируем выходной массив: копия target, в которую записываем предсказания только для пропусков
    out = work[TARGET_COL].astype(float)
    out.loc[mask] = pd.Series(ens, index=work.index).loc[mask]
    # Возвращаем результат в исходном порядке индексов и клипим в [0, 1]
    return out.loc[order].clip(0, 1)