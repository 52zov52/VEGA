# VEGA — Research Report (конкурсные данные)

## 1. Problem statement
Две связанные задачи: **A** — восстановление скрытых `primary_ndvi` (метрика RMSE,
`GapScore = round(30 * max(0, 1 − RMSE/0.10), 2)`); **B** — детекция негативных периодов
вегетации с объяснением причин. Единый pipeline: регион/полигон → спутник → очистка →
ряд → восстановление → аномалии → объяснение → визуализация.

## 2. Dataset
`data/train_dataset.csv` (99 955 строк, 39 полигонов, 2010–2024, дневной шаг),
`data/test.csv` (57 185 строк, 78 полигонов, 2010–2025). Скоринг — 3112 строк
с `is_synthetic_gap=True` (85% одиночные пропуски, все признаки в них замаскированы).
Ключевые находки EDA:
- `primary_ndvi` известен ⟺ доступен хотя бы один сенсор; в gaps все сенсоры/ERA5/климатология — NaN.
- `s2_ndvi == primary_ndvi` точь-в-точь (corr 1.0); landsat 0.993, modis 0.964.
- `status` (train-only): Штатное развитие / Угнетение биомассы / Критическая аномалия.
- Культуры: озимая пшеница, подсолнечник, пастбища/зерновые, зерновые.
- Day-to-day std соседних известных = 0.093 → пол интерполяции ≈ 0.066 (мы на нём).
- Test-known (17 641 строка, включая 2025 и 39 новых полигонов) — легитимный train-материал.

## 3. Baseline (validation 2024, synthetic gaps; RMSE)
| Метод | 1d | 2d | 3d | 7d | 14d | 30d |
|---|---:|---:|---:|---:|---:|---:|
| Nearest | 0.0851 | 0.0886 | 0.0958 | 0.1237 | 0.1817 | 0.2249 |
| Linear | 0.0742 | 0.0730 | 0.0716 | 0.0898 | 0.1045 | 0.1411 |
| Seasonal | 0.0731 | 0.0797 | 0.0782 | 0.1014 | 0.1083 | 0.1389 |
Ограничения: nearest рушится на длинных gaps; linear не знает сезонности/погоды;
seasonal игнорирует текущий год.

## 4. Hypotheses (итоги проверки)
1. GBM побьёт linear везде — ДА (residual-форма; plain-GBM с interp_now вырождался в тождество).
2. Temporal добавит на длинных gaps — ЧАСТИЧНО (MLP слаб, вес 0.2; на 30d temporal лучший из трёх).
3. Ансамбль ≥ лучшего компонента — ДА на 1–3d (0.0668 vs 0.0712).
4. Random split запрещён — time-forward (valid = последний год) + leave-polygon-out генератор.
5. Seed-bagging — НЕТ эффекта (ошибка = bias/шум, не variance).

## 5. Experiments
- Exp 01: таблица §3 + `experiments/ensemble.csv` (`scripts/train.py`).
- Exp 02 (бэкенды, 1d/3d): catboost 0.0731/0.0668, lightgbm 0.0730/0.0665, sklearn-hgb 0.0728/0.0665 —
  плато по алгоритму, выбран catboost (6 с обучение + early stopping).
- Exp 03 (веса, grid 0.05 на 1d-gaps — структура скрытого теста): (0.40 / 0.20 / 0.40).
- Exp 04 (абляции GBM): spatial_mean ±0, weather/small, лаги/сезонность — см. `reports/ablation.md`.
- Exp 05 (стратификация по days_since_obs): ensemble лучший во всех стратах, кроме 8–30d (gbm).

## 6. Финальная модель
`ensemble(0.40*residual-CatBoost + 0.20*TemporalMLP + 0.40*Seasonal)`, фичи `v20`
(56 колонок, только прошлое + двусторонняя интерполяция известных как prior).
Self-supervised fit (§11): обучение на синтетических gaps 1d/3d внутри train
(7727 точек), финал — train-known + test-known (48 161 строка истории, 2025 вкл.).
Valid 1d RMSE 0.0668 → GapScore 9.95. Ожидаемый тест ≈ тот же уровень
(медиана days_since_obs совпала: 3 и 3).
Артефакты: `models/gbm.joblib`, `models/temporal.joblib`, `models/meta.json`.

## 7. Error analysis
- Пол интерполяции: std соседних суток 0.093 → RMSE 1d ≈ 0.067 неулучшаем точечными методами.
- Худшие остатки — stale history (dso 31+: gbm 0.148 без seasonal, 0.088 в ансамбле).
- Temporal-MLP сглаживает пики; CatBoost доминирует на коротких gaps.
- Leave-polygon-out генератор готов (`splits.leave_polygon_out`); новые полигоны
  покрыты test-known историей и global-fallback признаками.

## 8. Anomaly examples (§18)
- Засуха: NDVI↓ NDWI↓ rain↓ temp↑ → «Гидрологический стресс», conf 0.82.
- Локальная: NDVI↓ при норме соседей/погоды → «Локальная проблема поля».
- Сенсорная: spike + низкое quality → «артефакт», conf 0.55.
Статусы train (`Угнетение биомассы`, `Критическая аномалия`) используются
детектором как weak labels для калибровки порогов (не как фичи — их нет в тесте).

## 9. Limitations
- Точечный потолок ≈ 0.067 задан физикой задачи (все same-day признаки скрыты).
- Temporal-бэкенд CPU/MLP; TCN включается при наличии torch.
- Сабмит: `submission.csv` (3112 строк) — `scripts/make_submission.py` + `validate_submission.py`.
