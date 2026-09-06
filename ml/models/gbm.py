"""Модель A — Gradient Boosting (§9) с graceful fallback (плавный переход между бэкендами).

Порядок моделизации: CatBoost -> LightGBM -> sklearn HistGradientBoostingRegressor.
Первые два используются при наличии в окружении; в Docker/community-сборке
гарантированно работает sklearn-бэкенд без GPU и без сети. Интерфейс един:
fit(X, y) / predict(X) / used_backend.

Переменная окружения VEGA_GBM_BACKEND=sklearn принудительно выбирает sklearn
(для абляций и воспроизводимости результатов).
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd


class GBMModel:
    """Класс для обучения и использования Gradient Boosting моделей.

    Поддерживает три бэкенда:
    1. CatBoost — самый производительный при наличии библиотеки
    2. LightGBM — альтернатива CatBoost
    3. sklearn HistGradientBoostingRegressor — всегда доступен как fallback

    Атрибуты:
        used_backend: строка, указывающая какой бэкенд был использован при обучении
        seed: случайный_seed для воспроизводимости результатов
    """

    used_backend: str = "none"

    def __init__(self, seed: int = 42):
        """Инициализация модели с заданным_seed для воспроизводимости.

        Args:
            seed: seed для случайных процессов при обучении (по умолчанию 42).
        """
        self.seed = seed
        self.model = None

    def fit(self, X: pd.DataFrame, y: pd.Series) -> "GBMModel":
        """Обучение модели с автоматический выбор бэкенда и fallback.

        Алгоритм обучения:
        1. Пробуем CatBoost — самый мощный при наличии библиотеки
        2. Если не удалось — пытаемся LightGBM
        3. Если и LightGBM не удалось — используем sklearn fallback

        Процесс подготовки данных:
        - Маскируем пропуски в целевой переменной (y)
        - Заполняем пропуски в признаках (X) медианой столбца или 0
        - Вырезаем train/valid split (90% train, последние 10% — valid)

        Args:
            X: DataFrame с признаками (может содержать NaN)
            y: Серия целевых значений (может содержать NaN)

        Returns:
            self: экземпляр модели с обучением backend'ом
        """
        mask = pd.Series(y).notna().to_numpy()
        X, y = X.iloc[mask].reset_index(drop=True) if hasattr(X, "iloc") else X, pd.Series(y).iloc[mask].reset_index(drop=True)
        # Заполняем пропуски: сначала медианой столбца, затем 0 если медиана тоже NaN
        Xn = X.fillna(X.median(numeric_only=True)).fillna(0)

        # ---- Попытка 1: CatBoost ----
        # CatBoost часто дает лучшее качество, но требует установленной библиотеки
        backend = os.getenv("VEGA_GBM_BACKEND", "").lower()
        force_sklearn = backend == "sklearn"  # принудительно sklearn
        skip_catboost = backend == "lightgbm"  # пропускаем CatBoost

        if not force_sklearn and not skip_catboost:
            try:
                from catboost import CatBoostRegressor

                # Гиперпараметры CatBoost:
                # iterations=3000: общее число итераций (early stopping остановит раньше)
                # depth=6: глубина дерева (умешеньба vs переобучение)
                # learning_rate=0.01: скорость обучения (маленький lr нужно много итераций)
                # l2_leaf_reg=3: L2 регуляризация штрафа за сложность листа
                # border_count=255: количество bin'ов для числовых признаков
                self.model = CatBoostRegressor(
                    iterations=3000, depth=6, learning_rate=0.01,
                    loss_function="RMSE", random_seed=self.seed, verbose=False,
                    early_stopping_rounds=200,
                    l2_leaf_reg=3,
                    border_count=255,
                )
                n = len(Xn)
                # cut точка разделения: 90% train, последние 10% — validation
                # минимум 5000 строк в валидации для статистически достоверного результата
                cut = max(int(n * 0.9), n - 5000)
                self.model.fit(Xn.iloc[:cut], y.iloc[:cut], eval_set=(Xn.iloc[cut:], y.iloc[cut:]))
                self.used_backend = "catboost"
                return self
            except Exception:
                # Если CatBoost не удалось (нет библиотеки или ошибка обучения),
                # переходим к следующему бэкенду
                pass

        # ---- Попытка 2: LightGBM ----
        if not force_sklearn:
            try:
                import lightgbm as lgb
                from lightgbm import LGBMRegressor

                # Гиперпараметры LightGBM:
                # n_estimators=6000: много деревьев, early stopping остановит раньше
                # num_leaves=31: сложность деревьев (2^5-1 = 31 terminal node)
                # learning_rate=0.01: медленное обучение, но стабильнее
                # subsample=0.8: bagging fraction - случайная подвыборка строк
                # colsample_bytree=0.7: случайная подвыборка признаков
                # min_child_samples=200: минимальное число объектов в листе (противо переобучению)
                # reg_lambda=10.0: L2 регуляризация на уровне градиента
                self.model = LGBMRegressor(
                    n_estimators=6000, num_leaves=31,
                    learning_rate=0.01, subsample=0.8, colsample_bytree=0.7,
                    min_child_samples=200, reg_lambda=10.0,
                    random_state=self.seed, verbose=-1,
                )
                n = len(Xn)
                cut = max(int(n * 0.9), n - 5000)
                self.model.fit(
                    Xn.iloc[:cut], y.iloc[:cut],
                    eval_set=[(Xn.iloc[cut:], y.iloc[cut:])],
                    callbacks=[lgb.early_stopping(200, verbose=False)],
                )
                self.used_backend = "lightgbm"
                return self
            except Exception:
                # Если LightGBM тоже не удалось, переходим к sklearn fallback
                pass

        # ---- Фолбэк 3: sklearn HistGradientBoostingRegressor ----
        # Всегда доступен, так как входит в состав scikit-learn
        # Используется как последний резервный вариант
        from sklearn.ensemble import HistGradientBoostingRegressor

        # Гиперпараметры sklearn HistGradientBoostingRegressor:
        # max_iter=1200: максимальное число итераций boosting
        # max_depth=8: максимальная глубина дерева
        # learning_rate=0.03: скорость обучения (немного выше, чем у CatBoost/LightGBM)
        # l2_regularization=5.0: L2 регуляризация (ridge penalty)
        # early_stopping="auto": автоматическая остановка при отсутствии улучшения
        self.model = HistGradientBoostingRegressor(
            max_iter=1200, max_depth=8, learning_rate=0.03,
            l2_regularization=5.0, early_stopping="auto", random_state=self.seed,
        )
        self.model.fit(Xn, y)
        self.used_backend = "sklearn-hgb"
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """Предсказание на новых данных.

        Алгоритм:
        1. Заполняет пропуски в X нулями (так как модель уже умеет работать с ними
           или использует свои внутренние механизмы работы с пропусками)
        2. Вызывает predict() обученной модели
        3. Клипит результат в диапазон [0, 1], так как NDVI всегда в этом диапазоне

        Args:
            X: DataFrame с новыми данными для предсказания

        Returns:
            numpy array с предсказаниями float, clipped в [0, 1].
        """
        Xn = X.fillna(0)  # Заменяем NaN на 0 (модель ожидает numeric вход)
        pred = np.asarray(self.model.predict(Xn), dtype=float)
        return np.clip(pred, 0.0, 1.0)  # NDVI всегда в диапазоне [0, 1]