# Experiment 01 — baselines на synthetic gaps (факт, demo-данные)

Команда: `python scripts/train.py` (источник demo, 8 полигонов, 2019–2024, шаг 7D).
Полная таблица — `experiments/ensemble.csv`.

| Метод | 1d | 3d | 7d | 14d | 30d |
|---|---:|---:|---:|---:|---:|
| Nearest | 0.0358 | 0.0464 | 0.0758 | 0.1431 | 0.1950 |
| Linear | 0.0228 | 0.0282 | 0.0440 | 0.0842 | 0.1256 |
| Seasonal | 0.0268 | 0.0375 | 0.0486 | 0.0869 | 0.1223 |
| GBM (sklearn-hgb) | 0.0137 | 0.0151 | 0.0142 | 0.0171 | 0.0221 |
| Temporal (mlp) | 0.0404 | 0.0408 | 0.0404 | 0.0478 | 0.0606 |
| Ensemble | 0.0137 | 0.0151 | 0.0142 | 0.0171 | 0.0221 |

Вывод: ML-ансамбль лучший на всех длинах; linear < nearest на коротких gaps,
как и ожидалось.

# Experiment 02 — CatBoost vs LightGBM vs HistGB

Бэкенды модели A при фиксированных признаках v17 и time-forward split.
В offline-окружении отработал `sklearn-hgb` (RMSE 7d = 0.0142). CatBoost/LightGBM
подхватываются автоматически при наличии в окружении (`ml/models/gbm.py`);
перезапуск `scripts/train.py` с ними обновит `models/meta.json` и таблицу.

# Experiment 03 — ensemble weights

Grid search весов w1/w2/w3 шагом 0.05 по RMSE на validation gaps 7d:
выбрано (1.00 / 0.00 / 0.00) — GBM доминирует на недельном demo-шаге,
temporal-MLP сглаживает пики. Схема весов конфигурируема (`.env` + `meta.json`)
и переподбирается тем же кодом на конкурсных данных.
