# 🚀 Как развернуть VEGA на Render (пошагово)

Этот гайд поможет вам быстро déployть проект VEGA на платформу Render.

## 📋 Подготовка

1. **Зарегистрируйтесь на render.com** - создайте аккаунт
2. **Подготовьте код** - убедитесь, что изменения закоммичены в GitHub

## 📦 Деплой

### Шаг 1: Создание нового веб-сервиса
1. Зайдите в панель управления Render
2. Нажмите "New +" → "Web Service"
3. Выберите "Docker" как окружение
4. Подключите ваш GitHub репозиторий VEGA

### Шаг 2: Авто-детекция конфигурации
Render автоматически обнаружит файл `render.yaml` в корне проекта и настроит следующие услуги:

## 🏗️ Конфигурация услуг

### 1. vega-api (FastAPI)
- **Dockerfile:** `docker/api.Dockerfile`
- **Порт:** 8000
- **Health Check:** `/api/health`
- **Переменные окружения:** Авто-загружены из `.env` файла

### 2. vega-db (PostgreSQL + PostGIS)
- **План:** Free
- **PostGIS:** Включен по умолчанию
- **Хранение:** `preserveStorage: true` (данные сохраняются)

### 3. vega-redis (Redis)
- **План:** Free
- **Использование:** Кэш и временные данные

### 4. vega-web (Next.js frontend)
- **Dockerfile:** `docker/web.Dockerfile`
- **Порт:** 3000
- **API URL:** Автоматически подставляется из сервиса vega-api

## 🔧 Настройка переменных окружения

Render автоматически внедряет переменные из `render.yaml`:

### Автоматически добавляемые:
- `DATABASE_URL` - строка подключения к PostgreSQL
- `REDIS_URL` - строка подключения к Redis

### Дополнительно нужно задать вручную (в Dashboard → Environment):
- `SENTINEL_API_URL` - URL Sentinel Hub (если нужна спутниковая съемка)
- `SENTINEL_API_KEY` - ключ Sentinel Hub
- `WEATHER_API_KEY` - ключ Open-Meteo (если нужен платный тариф, иначе используется бесплатный)
- `OVERPASS_API_URL` - Overpass API endpoints
- `NEXT_PUBLIC_API_URL` - будет подставлено автоматически

## 🌐 Доступ к приложению

После деплоя вы получите следующие URL:

- **API:** `https://vega-api.onrender.com`
- **Документация (Swagger):** `https://vega-api.onrender.com/docs`
- **Фронтенд:** `https://vega-web.onrender.com`

## ⚠️ Важные нюансы free-игры

1. **Sleep after 15 мин** - сервисы "засыпают" после 15 минут бездействия
2. **Первый запуск** - занимает 30-60 секунд (cold start)
3. **Переменные окружения** - проверьте в разделе "Environment" после деплоя
4. **База данных** - при удалении сервиса базы данных сохранятся (preserveStorage: true)

## 📝 Чек-лист перед запуском

- [x] Код загружен в GitHub
- [x] Файл `render.yaml` существует в корне
- [x] Файл `docker/api.Dockerfile` рабочий
- [x] Файл `docker/web.Dockerfile` рабочий
- [x] Переменные окружения настроены в Render Dashboard
- [x] SENTINEL_API_KEY вставлен если нужна спутниковая съемка

## 🛠️ Отладка

Если возникнут проблемы:

1. Проверьте логи в разделе "Logs" на Render
2. Убедитесь, что `docker/api.Dockerfile` правильный
3. Проверьте переменные окружения
4. Для локального тестирования: `docker-compose up -d`

## 📞 Поддержка

При проблемах с деплоем:
- Проверьте секцию "Environment" в настройках сервиса
- Убедитесь, что все required env vars установлены
- Посмотрите логи build/deploy процесса

---

**Сделано с ❤️ для VEGA - Vegetation Intelligence**