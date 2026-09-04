# VEGA // Vegetation Intelligence

Интеллектуальная система мониторинга сельхозтерриторий:
автоматический сбор ДЗЗ и метеоданных, восстановление пропусков NDVI,
детекция аномалий вегетации и объяснение вероятных причин.

Позиционирование: **DATA → TIME SERIES → ML → ANOMALY → EXPLANATION → DECISION**.
Главный технический KPI — минимальный RMSE восстановления `primary_ndvi`.

## 1. Requirements

- Python 3.11+ (проверено на 3.11–3.14), Node 20+, Docker 24+
- Без ключей API работает offline demo-режим (synthetic спутник + satellite-only аномалии)

## 2. Installation

```bash
git clone https://github.com/52zov52/VEGA.git && cd VEGA
cp .env.example .env
python -m pip install -r requirements.txt
cd apps/web && npm install && cd ../..
```

## 3. Environment variables

См. `.env.example`. Ключевые: `WEATHER_API_URL`, `SENTINEL_API_URL/KEY`,
`ENSEMBLE_W_*`, `ANOMALY_W_*`. Пустые ключи = fallback (не 500, а частичный анализ).

## 4. Run backend

```bash
uvicorn apps.api.main:app --reload --port 8000
# проверка: http://localhost:8000/api/health
```

## 5. Run frontend

```bash
cd apps/web && npm run dev
# http://localhost:3000
```

## 6. Load datasets

Положите конкурсный файл в `data/train_dataset.csv` (колонки `anon_polygon_id,date,primary_ndvi,...`)
и скрытый тест в `data/test.csv` (скоринг — строки с `is_synthetic_gap=True`).
Без них используется встроенный demo-генератор. `data/*.csv` в git не коммитятся.

## 7. Run model

```bash
py scripts/train.py --train data/train_dataset.csv --extra data/test.csv --out models
# --extra добавляет известные строки теста в финальный фит (валидация остаётся на train);
# без файлов — обучение на demo-датасете; результат: models/*.joblib + meta.json
# факт contest: valid 1d RMSE 0.0668, GapScore 9.95; таблица: experiments/ensemble.csv
```

## 8. Generate submission

```bash
py scripts/make_submission.py --test data/test.csv --out submission.csv
py scripts/validate_submission.py submission.csv
```

## 9. Run anomaly analysis

```bash
py scripts/demo_analysis.py
```

## 10. Run tests

```bash
py -m pytest tests/ -q
```

## Docker (воспроизводимость)

```bash
docker compose up --build
# web: http://localhost:3000, api: http://localhost:8000
```

## Структура

См. ТЗ §33: `apps/` (web, api), `ml/` (data, features, models, evaluation, inference),
`pipelines/` (satellite, weather, geodata, preprocessing), `services/` (anomaly, climatology, explanation),
`scripts/`, `experiments/`, `reports/`, `tests/`, `docker/`.

## Demo path (90 секунд)

Open app → Choose region → Choose field → Analyze → time series → restored gaps →
anomaly → Why? → explanation → compare → RMSE (experiments/gap_table.csv).
