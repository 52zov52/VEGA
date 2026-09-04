# Experiment 01 — baselines + модели на synthetic gaps (конкурсные данные, факт)

Команда: `python scripts/train.py --train data/train_dataset.csv --extra data/test.csv --out models`
Валидация: последний год (2024), 39 полигонов train. Полная таблица — `experiments/ensemble.csv`.

| Метод | 1d | 2d | 3d | 7d | 14d | 30d |
|---|---:|---:|---:|---:|---:|---:|
| Nearest | 0.0851 | 0.0886 | 0.0958 | 0.1237 | 0.1817 | 0.2249 |
| Linear | 0.0742 | 0.0730 | 0.0716 | 0.0898 | 0.1045 | 0.1411 |
| Seasonal | 0.0731 | 0.0797 | 0.0782 | 0.1014 | 0.1083 | 0.1389 |
| GBM residual-CatBoost | 0.0712 | 0.0713 | 0.0693 | 0.0855 | 0.0998 | 0.1338 |
| Temporal (MLP) | 0.0783 | 0.0765 | 0.0730 | 0.0873 | 0.1009 | 0.1280 |
| Ensemble (0.40/0.20/0.40) | 0.0668 | 0.0694 | 0.0672 | 0.0872 | 0.0988 | 0.1328 |

Вывод: ансамбль лучший на 1–3d (структура скрытого теста: 85% одиночных gaps).

# Experiment 02 — CatBoost vs LightGBM vs HistGB

Фичи v20, self-supervised fit на synthetic gaps, valid 2024:
CatBoost 1d 0.0731 / 3d 0.0668; LightGBM 0.0730 / 0.0665; sklearn-HGB 0.0728 / 0.0665.
Плато по алгоритму; выбран CatBoost (обучение ~6 с, early stopping по свежим датам).
Переключение — `VEGA_GBM_BACKEND=sklearn|lightgbm`.

# Experiment 03 — ensemble weights

Grid search весов шагом 0.05 по RMSE на validation gaps 1 день:
выбрано (0.40 / 0.20 / 0.40), valid 1d RMSE 0.0668, GapScore 9.95.
Веса хранятся в `models/meta.json` и используются инференсом.
