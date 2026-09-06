"""Финальный ансамбль (§9): w1*GBM + w2*Temporal + w3*Seasonal.

Веса подбираются на validation перебором (см. scripts/train.py),
по умолчанию — из .env (0.55 / 0.30 / 0.15). Клиппинг в [0, 1].

Стратегия per-gap-length: разные веса для разных длин gaps,
так как короткие gaps (1-3 дня) лучше interpolate GBM,
а длинные (7-30 дней) — Seasonalную нормальность.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class EnsembleWeights:
    """Базовые веса для взвешенного ансамбля из GBM, Temporal и Seasonal моделей.

    Атрибуты:
        w_gbm: вес модели Gradient Boosting Machine
        w_temporal: вес temporal (MLP) модели
        w_seasonal: вес seasonalной модели (база по климатической норме)
    """

    w_gbm: float = 0.55
    w_temporal: float = 0.30
    w_seasonal: float = 0.15

    def normalized(self) -> "EnsembleWeights":
        """Приводит сумму весов к 1.

        Если сумма весов <= 0, возвращает дефолтные веса (0.55 / 0.30 / 0.15).
        Иначе делит каждый вес на общую сумму.
        """
        s = self.w_gbm + self.w_temporal + self.w_seasonal
        if s <= 0:
            return EnsembleWeights(0.55, 0.30, 0.15)
        return EnsembleWeights(self.w_gbm / s, self.w_temporal / s, self.w_seasonal / s)


@dataclass
class EnsembleWeightsPerGap:
    """Класс для хранения весов ансамбля в зависимости от длины gap (пропуска в днях).

    Разные длины gaps требуют разных стратегий интерполяции:
    - 1-дневные gaps: GBM-heavy (ближайшие значения более надежны)
    - 2-3-дневные: баланс между GBM и Seasonal
    - 7-14-дневные: Seasonal важнее (сезонный цикл становится стабильнее)
    - 30-дневные: Seasonal-dominant (только климатическая норма)

    Атрибуты:
        gap_1d: веса для gaps длиной 1 день
        gap_2d: веса для gaps длиной 2 дня
        gap_3d: веса для gaps длиной 3 дня
        gap_7d: веса для gaps длиной 7 дней
        gap_14d: веса для gaps длиной 14 дней
        gap_30d: веса для gaps длиной 30 дней
    """

    gap_1d: EnsembleWeights = field(default_factory=lambda: EnsembleWeights(0.50, 0.30, 0.20))
    gap_2d: EnsembleWeights = field(default_factory=lambda: EnsembleWeights(0.48, 0.32, 0.20))
    gap_3d: EnsembleWeights = field(default_factory=lambda: EnsembleWeights(0.45, 0.35, 0.20))
    gap_7d: EnsembleWeights = field(default_factory=lambda: EnsembleWeights(0.40, 0.30, 0.30))
    gap_14d: EnsembleWeights = field(default_factory=lambda: EnsembleWeights(0.35, 0.30, 0.35))
    gap_30d: EnsembleWeights = field(default_factory=lambda: EnsembleWeights(0.30, 0.30, 0.40))

    def get_weights(self, gap_len: int) -> EnsembleWeights:
        """Получить веса EnsembleWeights для данной длины gap (в днях).

        Стратегия отбора весов basada на empirical findings:
        - Короткие gaps (1-3 дня): GBM contributes больше, так как
          близкие наблюдения все еще актуальны
        - Длинные gaps (7-30 дней): Seasonal contributes больше,
          так как близкие наблюдения больше не репрезентативны,
          а сезонный цикл становится определяющим

        Args:
            gap_len: длина пропуска в днях (1, 2, 3, 7, 14, 30)

        Returns:
            EnsembleWeights с оптимальными весами для данной длины gap.
        """
        if gap_len <= 1:
            return self.gap_1d.normalized()
        elif gap_len <= 2:
            return self.gap_2d.normalized()
        elif gap_len <= 3:
            return self.gap_3d.normalized()
        elif gap_len <= 7:
            return self.gap_7d.normalized()
        elif gap_len <= 14:
            return self.gap_14d.normalized()
        else:
            # gap_len >= 30
            return self.gap_30d.normalized()


def ensemble_predict(
    p_gbm: np.ndarray,
    p_temporal: np.ndarray,
    p_seasonal: np.ndarray,
    weights: EnsembleWeights | EnsembleWeightsPerGap | None = None,
    gap_lens: np.ndarray | None = None,
) -> np.ndarray:
    """Взвешенный ансамбль: kombinatsiya prediktsii GBM, Temporal и Seasonal.

    Args:
        p_gbm: предсказания от GBM модели
        p_temporal: предсказания от temporal (MLP) модели
        p_seasonal: предсказания от seasonalной модели
        weights: веса ансамбля. Если передается EnsembleWeightsPerGap,
            смотрится gap_lens для выбора весов per gap length.
        gap_lens: массив длин gaps для каждой строки данных.
            Нужен для per-gap-length стратегии.

    Returns:
        Взвешенное предсказание как комбинация трех моделей.
        Результат clips в диапазон [0, 1], так как NDVI всегда в этом диапазоне.

    Стратегия взвешивания:
    - Если weights — EnsembleWeightsPerGap и есть gap_lens:
        выбираются веса в зависимости от длины каждого gap.
    - Иначе используются глобальные веса (или переданные explicitly).
    """
    if isinstance(weights, EnsembleWeightsPerGap) and gap_lens is not None:
        # Per-gap-length strategy: select weights based on each gap's length
        ws_list = []
        for gl in gap_lens:
            w = weights.get_weights(int(gl)).normalized()
            ws_list.append((w.w_gbm, w.w_temporal, w.w_seasonal))
        # Применяем per-row weights (vectorized approach for efficiency)
        out = np.full_like(p_gbm, np.nan, dtype=float)
        for i in range(len(gap_lens)):
            wgbm, wtem, wsea = ws_list[i]
            gbm_i = np.asarray(p_gbm[i], dtype=float)
            tmp_i = np.asarray(p_temporal[i], dtype=float)
            sea_i = np.asarray(p_seasonal[i], dtype=float)
            ws = np.array([wgbm, wtem, wsea], dtype=float)
            stack = np.vstack([gbm_i, tmp_i, sea_i])
            # Проверка на finite значения: 0 * NaN = NaN, поэтому веса
            # перераспределяются на доступные компоненты (важно для полностью
            # скрытых рядов, где seasonal не может построиться).
            valid = np.isfinite(stack)
            wsum = (valid * ws[:, None]).sum(axis=0)
            comp = (np.where(valid, stack, 0.0) * ws[:, None]).sum(axis=0)
            out[i] = np.divide(comp, wsum, out=np.full(1, 0.5), where=wsum > 0)
        return np.clip(out, 0.0, 1.0)
    else:
        # Global weights strategy (классический случай)
        w = (weights or EnsembleWeights()).normalized()
        gbm = np.asarray(p_gbm, dtype=float)
        tmp = np.asarray(p_temporal, dtype=float)
        sea = np.asarray(p_seasonal, dtype=float)
        ws = np.array([w.w_gbm, w.w_temporal, w.w_seasonal], dtype=float)
        stack = np.vstack([gbm, tmp, sea])
        valid = np.isfinite(stack)
        wsum = (valid * ws[:, None]).sum(axis=0)
        # Устойчивость к NaN: если wsum == 0, используем fallback значение 0.5
        out = (np.where(valid, stack, 0.0) * ws[:, None]).sum(axis=0)
        out = np.divide(out, wsum, out=np.full_like(out, 0.5), where=wsum > 0)
        return np.clip(out, 0.0, 1.0)


def grid_search_weights(
    y_true: np.ndarray,
    p_gbm: np.ndarray,
    p_temporal: np.ndarray,
    p_seasonal: np.ndarray,
) -> EnsembleWeights:
    """Полный перебор весов с шагом 0.05 по RMSE на validation выборке.

    Производит exhaustive search по всем combinaциям весов с шагом 0.05,
    сохраняя те, что дают наименьший RMSE на валидационных данных.

    Алгоритм:
    1. Перебирает a (вес GBM) от 0.0 до 1.0 с шагом 0.05
    2. Перебирает b (вес Temporal) от 0.0 до 1.0 - a с шагом 0.05
    3. c = 1.0 - a - b (вес Seasonal), ограничивается [0, 1]
    4. Вычисляет RMSE для каждой combinaции
    5. Сохраняет лучший результат

    Args:
        y_true: истинные значения для validation
        p_gbm: предсказания GBM
        p_temporal: предсказания Temporal
        p_seasonal: предсказания Seasonal

    Returns:
        Оптимальные веса EnsembleWeights, минимизирующие RMSE.
    """
    from ml.evaluation.metrics import rmse

    best: EnsembleWeights = EnsembleWeights()
    best_score = float("inf")
    steps = [i / 20 for i in range(21)]  # шаг 0.05
    for a in steps:
        for b in steps:
            c = 1.0 - a - b
            if c < -1e-9 or c > 1:
                # Веса выходят за пределы [0, 1], пропускаем
                continue
            score = rmse(y_true, ensemble_predict(p_gbm, p_temporal, p_seasonal, EnsembleWeights(a, b, max(c, 0))))
            if score < best_score:
                best_score = score
                best = EnsembleWeights(a, b, max(c, 0))
    return best.normalized()


# Стратификация весов по давности последнего наблюдения (days_since_obs):
# Свежим точкам важнее GBM/interp, далёким — seasonal. Границы из ablation studies.
# dso1-2: very recent observations (0-2 дня since last observation)
# dso3-7: medium recency (3-7 дней)
# dso8+: old observations (8+ дней, seasonal dominates)
DSO_BINS: tuple[tuple[str, int, int | None], ...] = (
    ("dso1-2", 0, 2),
    ("dso3-7", 3, 7),
    ("dso8+", 8, None),
)


def dso_bin_names(dso: np.ndarray) -> np.ndarray:
    """Конвертирует массив DSO (days since observation) в названия бинов.

    Args:
        dso: массив целых чисел, дней с последнего наблюдения

    Returns:
        массив строк с названиями бинов (dso1-2, dso3-7, dso8+)
    """
    dso = np.asarray(dso, dtype=float)
    out = np.full(dso.shape, "dso8+", dtype=object)
    out[dso <= 2] = "dso1-2"
    out[(dso >= 3) & (dso <= 7)] = "dso3-7"
    return out


def apply_stratified(
    p_gbm: np.ndarray,
    p_temporal: np.ndarray,
    p_seasonal: np.ndarray,
    dso: np.ndarray | None,
    weights_by_bin: dict[str, EnsembleWeights] | None,
    fallback: EnsembleWeights | None = None,
) -> np.ndarray:
    """Взвешивание по бинам dso (days since observation).

    Стратификация позволяет использовать разные веса ансамбля
    для точек с разным возрастом наблюдений.

    Логика:
    - Свежие наблюдения (dso1-2): GBM важнее, так как данные свежие
    - Средние (dso3-7): баланс между GBM и Seasonal
    - С旧观测 (dso8+): Seasonal dominates, так как данные давно устарели

    Args:
        p_gbm: предсказания GBM
        p_temporal: предсказания Temporal
        p_seasonal: предсказания Seasonal
        dso: массив days_since_obs для каждой точки (может быть None)
        weights_by_bin: словарь весов по бинам DSO
        fallback: fallback-веса, если dso отсутствует или weights_by_bin пуст

    Returns:
        Массив предсказаний с примененной стратификацией.
        Без dso/весов возвращает обычный глобальный ансамбль.
    """
    if not weights_by_bin or dso is None:
        return ensemble_predict(p_gbm, p_temporal, p_seasonal, fallback)
    names = dso_bin_names(dso)
    out = np.zeros_like(np.asarray(p_gbm, dtype=float))
    for name, _, _ in DSO_BINS:
        m = names == name
        if not m.any():
            continue
        w = weights_by_bin.get(name) or fallback
        out[m] = ensemble_predict(
            np.asarray(p_gbm, dtype=float)[m],
            np.asarray(p_temporal, dtype=float)[m],
            np.asarray(p_seasonal, dtype=float)[m],
            w,
        )
    return out