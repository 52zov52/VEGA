# VEGA // Vegetation Intelligence

Интеллектуальная система мониторинга сельхозтерриторий:
автоматический сбор ДЗЗ и метеоданных, восстановление пропусков NDVI,
детекция аномалий вегетации и объяснение вероятных причин.

Позиционирование: **DATA → TIME SERIES → ML → ANOMALY → EXPLANATION → DECISION**.
Главный технический KPI — минимальный RMSE восстановления `primary_ndvi`.

> Инструкция ниже самодостаточна: по ней решение запускается без
> дополнительных правок, а базовые сценарии проходятся без обращения
> к команде. Проверено на Windows 11 + Python 3.12 + Node 24
> (бэкенд/фронт подняты, тесты `38 passed`, демо-анализ отрабатывает).

---

## 1. Стек

| Слой | Технологии |
|---|---|
| Backend | Python 3.11–3.14, FastAPI 0.115, Uvicorn, Pydantic v2 + pydantic-settings |
| Frontend | Node 20+, Next.js 14 (App Router), React 18, TypeScript |
| Карта | `react-globe.gl` + `three`, `maplibre-gl` |
| Графики | Apache ECharts 5 |
| ML | CatBoost, LightGBM, PyTorch, scikit-learn, SciPy, pandas, NumPy |
| Геоданные | GeoPandas, Shapely, PyProj, Rasterio, xarray / rioxarray |
| HTTP-клиент провайдеров | httpx |
| Инфра (опционально, только Docker) | PostGIS 16, Redis 7 |
| Тесты | pytest (38 тестов) |

Без ключей API и без Docker всё работает в **offline demo-режиме**:
синтетический спутник, погода NASA POWER / fallback, контуры полей
из OpenStreetMap (Overpass) либо встроенная демо-сетка.

---

## 2. Структура проекта

```text
VEGA/
├── apps/
│   ├── api/                  # Backend (FastAPI)
│   │   ├── main.py           # 15 REST-эндпоинтов: health, регионы, поля,
│   │   │                     # полигоны, анализ, ряды, аномалии, объяснения, прогноз
│   │   ├── engine.py         # Конвейер анализа: спутник → погода → восстановление
│   │   │                     # ряда → детекция → объяснение + экспериментальный прогноз
│   │   ├── schemas.py        # Pydantic-схемы запросов
│   │   └── config.py         # Настройки через .env (со значениями по умолчанию)
│   └── web/                  # Frontend (Next.js)
│       ├── app/
│       │   ├── page.tsx      # Главная: 3D-глобус + панели (регионы, поля,
│       │   │                 # свой полигон, слои, сравнение)
│       │   ├── field/[id]/page.tsx  # Страница анализа поля: KPI, динамика NDVI,
│       │   │                        # прогноз, аномалии, рекомендации, экспорт CSV
│       │   └── layout.tsx    # Корневой layout (viewport, theme-color, шрифты)
│       ├── components/       # Globe, KPI, AnomalyCard, Modal, UIStates
│       ├── lib/api.ts        # Клиент backend API (fetchAnalysis, fetchForecast)
│       └── styles.css        # Дизайн-система + адаптив (ПК / планшет / телефон)
├── ml/
│   ├── data/                 # Контракт данных (колонки, TARGET_COL=primary_ndvi)
│   ├── features/             # Признаки для восстановления ряда
│   ├── models/               # GBM / temporal / seasonal ансамбль
│   ├── evaluation/           # Метрики (RMSE, GapScore)
│   └── inference/            # predict_gaps — восстановление пропусков
├── pipelines/
│   ├── satellite/            # Провайдеры ДЗЗ (Sentinel Hub / Landsat / MODIS / demo)
│   ├── weather/              # Погода (Open-Meteo / NASA POWER / fallback)
│   ├── geodata/              # Регионы, контуры полей (Overpass / Nominatim / demo)
│   └── preprocessing/        # Чистка и склейка рядов
├── services/
│   ├── anomaly/              # Детекция аномалий вегетации
│   ├── climatology/          # Климатическая норма NDVI
│   └── explanation/          # Объяснение причин («почему»)
├── scripts/
│   ├── train.py              # Обучение ансамбля (→ models/*.joblib + meta.json)
│   ├── demo_analysis.py      # Быстрый сквозной анализ без фронта
│   ├── make_submission.py    # Генерация submission.csv
│   ├── validate_submission.py# Проверка submission.csv
│   ├── eval_anomaly.py       # Оценка качества детекции аномалий
│   └── sentinel_probe.py     # Проверка доступа к Sentinel Hub
├── tests/                    # test_api, test_anomaly, test_ensemble,
│                             # test_features, test_metrics, test_providers
├── docker/                   # api.Dockerfile, web.Dockerfile
├── experiments/              # ensemble.csv, baseline.csv, скрипты тюнинга
├── reports/                  # ablation.md, anomaly.md, data_pipeline.md,
│                             # experiment_01.md, RESEARCH.md и др.
├── data/                     # (в git не коммитится) datasets, кэш, polygons.json
├── models/                   # (в git не коммитятся) артефакты обучения
├── docker-compose.yml        # db (PostGIS) + redis + api + web
├── requirements.txt          # Зависимости backend/ML
└── pytest.ini                # testpaths = tests
```

Хранилище пользовательских полигонов: память + персистентность
в `./data/polygons.json` (переживает рестарт API; PostGIS-контракт —
следующим шагом без смены REST API).

---

## 3. Быстрый старт (локально, без Docker)

Требования: **Python 3.11+**, **Node 20+**. Порты: **8000** (API), **3000** (web).

```bash
git clone https://github.com/52zov52/VEGA.git
cd VEGA

# 1. Переменные окружения (Windows: copy .env.example .env)
cp .env.example .env

# 2. Backend
python -m pip install -r requirements.txt
python -m uvicorn apps.api.main:app --reload --port 8000
# проверка: http://localhost:8000/api/health  ->  {"status":"ok","service":"vega-api"}
# Swagger UI: http://localhost:8000/docs

# 3. Frontend (второе окно терминала)
cd apps/web
npm install
npm run dev
# открыть: http://localhost:3000
```

Переменная `NEXT_PUBLIC_API_URL` (по умолчанию `http://localhost:8000`)
читается фронтом при старте `npm run dev` — после её смены перезапустите dev-сервер.

### Замечания для Windows

- Если PowerShell блокирует запуск `npm`/`npx` (ошибка про
  `Execution_Policies`), выполняйте команды через `cmd`:
  `cmd /c "cd /d <путь>\VEGA\apps\web && npm run dev"`.
- Python ставить с python.org с галкой **ADD TO PATH**; дальше команды
  как выше (`python`, `pip`).
- Долгоживущие серверы удобно держать в двух отдельных окнах `cmd`:
  `VEGA-API` и `VEGA-WEB`.

### Запуск через Docker (альтернатива)

Нужен Docker 24+. Переменные берутся из `.env`:

```bash
cp .env.example .env
docker compose up --build
# web: http://localhost:3000, api: http://localhost:8000
```

---

## 4. Переменные окружения

Полный список — в `.env.example`. Ключевые:

| Переменная | Назначение | Без значения |
|---|---|---|
| `WEATHER_API_URL` | Погода (по умолчанию Open-Meteo) | fallback / NASA POWER |
| `SENTINEL_SH_CLIENT_ID` / `SENTINEL_SH_CLIENT_SECRET` | Реальный Sentinel-2 L2A ряд через Sentinel Hub | demo-генератор |
| `OVERPASS_API_URL` | Зеркала Overpass для контуров OSM (через запятую) | демо-сетка полей |
| `NOMINATIM_URL` | Геокодер для поиска регионов | только встроенные регионы |
| `DATABASE_URL` / `REDIS_URL` | PostGIS / Redis (нужны только в Docker) | файловое хранение + память |
| `ENSEMBLE_W_*`, `ANOMALY_W_*` | Веса ансамбля и детектора | значения по умолчанию из отчёта |
| `NEXT_PUBLIC_API_URL` | Адрес API для фронта | `http://localhost:8000` |

Пустые ключи — это штатный режим, а не ошибка: API возвращает
частичный анализ с полем `warnings`, а не HTTP 500.

---

## 5. REST API (кратко)

Базовый URL: `http://localhost:8000`. Интерактивная документация: `/docs`.

| Метод | Путь | Назначение |
|---|---|---|
| GET | `/api/health` | Проверка живости |
| POST | `/api/regions/search` | Поиск регионов (`{"query": "..."}`), 27 встроенных + Nominatim |
| POST | `/api/regions` | Новый регион в любой точке планеты (`name`, `center: [lat, lon]`) |
| DELETE | `/api/regions/{region_id}` | Удаление только кастомного региона |
| GET | `/api/regions/{region_id}/fields?limit=` | Контуры полей (`source: overpass` или `demo`) |
| POST | `/api/polygons` | Сохранить свой GeoJSON Polygon (≥3 точек, bbox ≤10°, ≥0.1 га) |
| GET | `/api/polygons` | Список своих полигонов |
| PATCH | `/api/polygons/{pid}` | Переименование (`name`, 1–80 символов) |
| DELETE | `/api/polygons/{pid}` | Удаление полигона |
| POST | `/api/analyze` | Запуск анализа (`polygon_id`, `region_id`, `start/end`, `lat/lon`) |
| GET | `/api/analyze/{aid}/timeseries` | Временной ряд NDVI/осадков |
| GET | `/api/analyze/{aid}/anomalies` | Найденные аномалии |
| GET | `/api/analyze/{aid}/explanation` | Объяснения причин |
| GET | `/api/analyze/{aid}/forecast?horizon=` | Прогноз NDVI (эксперимент) |
| POST | `/api/prediction` | Восстановление одной точки `primary_ndvi` (нужна обученная модель, иначе 503) |

Примеры:

```bash
curl http://localhost:8000/api/health
curl -X POST http://localhost:8000/api/regions/search \
  -H "Content-Type: application/json" -d "{\"query\": \"\"}"
curl "http://localhost:8000/api/regions/rostov/fields?limit=3"
```

Первый запрос контуров региона может идти до ~30 секунд (опрос Overpass
с кэшированием) — это нормально.

---

## 6. Базовые сценарии проверки (для эксперта)

### Сценарий A — запуск и здоровье системы (~2 мин)

1. Поднимите API и web по разделу 3.
2. `GET /api/health` → `{"status":"ok","service":"vega-api"}`.
3. Откройте `http://localhost:3000` — загружается тёмная тема VEGA,
   хедер, 3D-глобус, левая панель.
4. Запустите тесты: `python -m pytest tests/ -q` → `38 passed`.

### Сценарий B — регион → поле → анализ (~3 мин)

1. В панели «Регион» выберите «Ростовская область»
   (первая загрузка контуров — до ~30 сек, бейдж `◉ OSM-контуры`).
2. В списке «Поля» кликните поле → камера долетает, открывается попап.
3. Нажмите **«Анализ поля»** → dive-переход → страница поля:
   - блок «Ключевые показатели» (NDVI, отклонение, риск, качество);
   - график «Динамика вегетации» (NDVI / норма / осадки / аномалии);
   - блок «Прогноз NDVI» (эксперимент, с коридором);
   - «Аномалии», «Детали и рекомендации».
4. Кнопка **⬇ CSV** скачивает ряд с прогнозом (`date,ndvi_observed,...`).
5. **← Карта** возвращает на глобус.

### Сценарий C — свой полигон

1. **✏ Нарисовать** → кликайте ≥3 точек по глобусу
   (счётчик и площадь в гектарах — вживую).
2. **Готово** → полигон сохраняется (`AOI-XXXXX`), камера летит к нему.
3. В «Сохранённые»: переименование по клику на название, «Выбрать», «Удалить».
4. Полигоны переживают рестарт API (`data/polygons.json`).

### Сценарий D — сравнение полей

1. В списке полей отметьте «сравнить» у 2–5 полей.
2. **Сравнить (N)** → модальное окно: NDVI, отклонение, риск, качество.

### Сценарий E — свой регион в любой точке планеты

1. **＋ регион** → название + `lat`/`lon` → **Добавить**.
2. Контуры вокруг центра находятся автоматически; лишний регион удаляется
   кнопкой «Удалить регион». Поиск выше ищет и по Nominatim (метка 🌍).

### Сценарий F — мобильный адаптив

1. Откройте DevTools → Device Toolbar (или реальный телефон
   в том же Wi-Fi: `http://<IP-ПК>:3000`).
2. ≤1024px: панели уезжают в выдвижной drawer (бургер `☰` в хедере),
   поверх карты — круглые кнопки `☰` / `✏`, выбранное поле — нижняя
   карточка с крупной кнопкой **«Анализ →»**.
3. Проверьте: drawer открывается/закрывается, рисование тапами работает,
   таблица сравнения и страница поля не дают горизонтального скролла.

### Сценарий G — ML-конвейер (опционально)

```bash
# Сквозной анализ без фронта (offline demo):
python scripts/demo_analysis.py
# -> OK: KPI={... level: 'watch'} ... sources={'satellite': 'demo(fallback)', ...}

# Датасеты (в git не коммитятся): data/train_dataset.csv
# (колонки anon_polygon_id,date,primary_ndvi,...) и data/test_features_1.csv.
# Без них обучение идёт на demo-датасете.
python scripts/train.py --train data/train_dataset.csv --extra data/test_features_1.csv --out models
python scripts/make_submission.py --test data/test_features_1.csv --out submission.csv
python scripts/validate_submission.py submission.csv
```

Факт контеста (зафиксирован в `experiments/ensemble.csv`):
valid 1d RMSE **0.0636**, GapScore **10.91**
(pooled 3 сида + стратификация dso).

---

## 7. Дизайн и адаптив

- Тёмная тема «Black & White + Earth Observation», шрифт Montserrat.
- Десктоп (>1024px): сайдбар 300px слева + глобус справа.
- Планшет/телефон (≤1024px): карта на весь экран, панели — выдвижной
  drawer; тач-таргеты ≥40px; модалка сравнения — нижний шит;
  `viewport-fit=cover` + `safe-area-inset` для чёлки.
- Страница поля: KPI-сетка, `stat-strip` 5→2 колонки, графики ECharts
  с ресайзом, рекомендации по уровню риска.

---

## 8. Устранение неполадок

| Симптом | Причина и решение |
|---|---|
| `curl: (000)` на `:8000` | API не запущен. Поднимите: `python -m uvicorn apps.api.main:app --reload --port 8000` из корня |
| Пустой список полей / `Не удалось загрузить поля` | Нет связи фронт→API. Проверьте `NEXT_PUBLIC_API_URL` и перезапустите `npm run dev` |
| Первый запрос полей висит ~30 сек | Норма: опрос Overpass + кэш. Повторные — быстро |
| `◇ демо-сетка` вместо `◉ OSM-контуры` | Overpass недоступен — штатный fallback |
| `503 Модель не обучена` на `/api/prediction` | Запустите `scripts/train.py` (анализ/графики работают и без модели: `restore: linear`) |
| PowerShell не даёт запустить `npm` | Работайте через `cmd` (см. раздел 3) |
| Порт занят (`EADDRINUSE` / `[Errno 10048]`) | Найдите процесс: `netstat -ano \| findstr :3000` и завершите его, либо смените порт (`--port 8001` + `NEXT_PUBLIC_API_URL`) |

---

## 9. Демо-путь за 90 секунд

Открыть app → выбрать регион → выбрать поле → Анализ → ряд →
восстановленные пропуски → аномалия → объяснение «почему» →
сравнение полей → RMSE (`experiments/gap_table.csv`).
