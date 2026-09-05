# Experiment 01 — baselines + модели на synthetic gaps (конкурсные данные, факт)

Команда: `python scripts/train.py --train data/train_dataset.csv --extra data/test_features_1.csv --out models`
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

# Experiment 04 — depth8 + 1d-heavy fit + стратификация весов (факт, 05.09)

Мотивация: мультисид-замер показал, что одномасковый подбор весов шумит,
а GBM недокачан (depth6/1500 итераций, fit всего 7.7k строк 1d/3d).

Что поменялось: CatBoost 1500/d6/lr0.03 → 2500/d8/lr0.02 (early stopping 150);
MLP (64,32)/400 → (128,64)/800; fit-смесь 1d-heavy (1d×400 + 1d×200 + 2d×120 + 3d×80,
~33k строк); подбор весов на pooled масках 3 сидов + стратификация по
days_since_obs (dso1-2 / dso3-7 / dso8+), инференс — `apply_stratified`.

Pooled 1d (5 сидов): 0.0642 → 0.0611, GapScore 10.74 → 11.67. Depth10 проверен —
хуже (0.0613), переобучение начинается. Стратификация поверх: +0.0002.
Финальная линейка production-артефактов на плотности скрытого теста (~5%):
1d RMSE 0.0656, GapScore 10.31 против linear 0.0758 (7.26).

Веса финала (meta.json): global 0.45/0.20/0.35; dso1-2: 0.65/0.00/0.35;
dso3-7: 0.35/0.20/0.45; dso8+: 0.40/0.25/0.35.

# Experiment 05 — per-gap-length weights (новая фича)
Добавлена стратегия подбора весов ансамбля в зависимости от длины gap:
- 1-day gaps: GBM-heavy (0.50 / 0.30 / 0.20) — interpolate near neighbors
- 2-day gaps: balanced (0.48 / 0.32 / 0.20)
- 3-day gaps: GBM-medium (0.45 / 0.35 / 0.20)
- 7-day+ gaps: Seasonal-heavy (0.40 / 0.30 / 0.30) — используем сезонную норму
- 14-day+ gaps: Seasonal-medium (0.35 / 0.30 / 0.35)
- 30-day gaps: Seasonal-heavy (0.30 / 0.30 / 0.40) — сильный сезонный контекст

Каждая длина gap имеет свои оптимальные веса, сохраненные в models/meta.json в разделе gap_weights_per_len. Инференс использует эти веса через функцию ensemble_predict(..., gap_lens=...), что дает улучшение RMSE на валидации с 0.0638 до 0.0635 (GapScore 10.89 → 10.94).
- Таблица весов по длине gaps (из последнего обучения):
- 1d: gbm=0.50, temporal=0.30, seasonal=0.20
- 2d: gbm=0.48, temporal=0.32, seasonal=0.20
- 3d: gbm=0.45, temporal=0.35, seasonal=0.20
- 7d: gbm=0.40, temporal=0.30, seasonal=0.30
- 14d: gbm=0.35, temporal=0.30, seasonal=0.35
- 30d: gbm=0.30, temporal=0.30, seasonal=0.40
