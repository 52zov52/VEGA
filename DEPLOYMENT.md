# 🚀 Как развернуть VEGA на Render (пошагово на русском)

Деплой идёт через **нативные рантаймы** (Python + Node), как локальный запуск
через `uvicorn` — Docker не используется.

## ❓ Надо ли что-то вводить в переменные?

**Почти ничего.** Версия Python зафиксирована файлом `.python-version` (3.11),
остальное уже прописано в `render.yaml`. Единственное, что Render спросит при
установке, — два **необязательных** секрета Sentinel Hub. Их можно оставить
пустыми: API запустится в demo/fallback режиме (погода — бесплатный Open-Meteo
без ключа, спутник — синтетические данные).

| Переменная | Откуда берётся | Вводить вручную? |
|---|---|---|
| Python `3.11` | из файла `.python-version` | нет |
| `APP_ENV`, `WEATHER_API_URL`, `OVERPASS_API_URL` | из `render.yaml` | нет |
| `NEXT_PUBLIC_API_URL` | подставляется сам из адреса API | нет |
| `SENTINEL_SH_CLIENT_ID` | спросит Render при установке | **можно пусто** (тогда demo-режим) |
| `SENTINEL_SH_CLIENT_SECRET` | спросит Render при установке | **можно пусто** (тогда demo-режим) |

База Postgres и Redis **не нужны** — код их не использует
(полигоны хранятся в `./data/polygons.json`).

## 📦 Деплой

### Вариант A. У тебя уже есть созданный Python-сервис (быстрее)
1. Дождись, пока GitHub подтянет свежий коммит (с файлом `.python-version`),
   либо нажми **Manual Deploy** на сервисе.
2. Проверь **Settings** сервиса:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn apps.api.main:app --host 0.0.0.0 --port $PORT`
   
   ⚠️ Именно `$PORT`, а не `8000` — порт назначает Render, иначе health-check не пройдёт.
3. Нажми **Manual Deploy → Clear build cache & Deploy** (очистка кэша важна:
   там остались артефакты сборки под Python 3.14).

### Вариант B. Через Blueprint (создаст API + фронтенд сразу)
1. **New + → Blueprint** → репозиторий `52zov52/VEGA`, ветка `master` → **Apply**.
2. Секреты Sentinel оставить пустыми → Apply.
3. Получишь 2 сервиса: `vega-api` (Python) и `vega-web` (Node).

### Почему раньше падало
Render по умолчанию ставил Python 3.14, а зафиксированные версии пакетов
(`pandas 2.2.3`, `scipy 1.14.1`…) под него не имеют готовых колёс — pip пытался
собрать их из исходников и падал на `scipy` (нет Fortran-компилятора
`gfortran`). Файл `.python-version` с `3.11` решает это: под 3.11 колёса есть
у всех зависимостей, включая `torch`.

## ⏳ Сколько ждать
Первая сборка — **10–20 минут** (тянется большой `torch`, плюс `catboost`,
`lightgbm`). Следить во вкладке **Logs**. Успех = статус **Live**.

## 🌐 Адреса после деплоя
- **API:** `https://vega-api.onrender.com`
- **Документация (Swagger):** `https://vega-api.onrender.com/docs`
- **Фронтенд:** `https://vega-web.onrender.com`

Точные адреса покажет дашборд (суффикс может отличаться).

## ⚠️ Важно
1. **Free-план засыпает** после ~15 минут без запросов. Первый запрос после
   сна идёт 30–60 секунд (cold start) — нормально.
2. **Секреты в `.env` засвечены.** `SENTINEL_SH_CLIENT_ID` и
   `SENTINEL_SH_CLIENT_SECRET` лежат в git-истории открытым текстом —
   перевыпусти их в кабинете Sentinel Hub. В `render.yaml` секреты НЕ
   захардкожены, они вводятся только через дашборд.
3. Локальный запуск как раньше: `uvicorn apps.api.main:app --host 0.0.0.0 --port 8000`

## 🛠️ Если что-то пошло не так
1. Смотри хвост **Logs**: `Build failed` на `pip install` = не та версия
   Python (проверь, что в корне репозитория есть `.python-version` и кэш
   сборки очищен); `Deploy failed` / красный health-check = смотри runtime-логи,
   обычно виноват старт-команд без `$PORT`.
2. Локальная проверка: `python --version` (нужен 3.11), затем
   `pip install -r requirements.txt`.

---

**Сделано с ❤️ для VEGA — Vegetation Intelligence**
