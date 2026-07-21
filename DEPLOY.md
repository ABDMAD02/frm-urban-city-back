# Деплой Urban City Backend в DigitalOcean

Пошаговая инструкция для **App Platform** (рекомендуется). Бэкенд упакован в Docker, стартует через **gunicorn + uvicorn workers**.

> **Важно:** при `USE_DB=1` (или `auto` + production) данные хранятся в **PostgreSQL** и переживают рестарт. In-memory — только для локального dev без БД.

| `USE_DB` | `DATABASE_URL` | Хранилище |
|---|---|---|
| `0` | — | in-memory |
| `1` | обязателен | PostgreSQL |
| `auto` | в production | PostgreSQL |
| `auto` | нет (dev) | in-memory |

---

## Что уже подготовлено в репозитории

| Файл | Назначение |
|---|---|
| `Dockerfile` | Production-образ (Python 3.12, non-root user, healthcheck) |
| `docker-compose.yml` | Локальная проверка «как на проде» (API + Postgres) |
| `scripts/start.sh` | Миграции Alembic (если `RUN_MIGRATIONS=1`) + gunicorn |
| `.do/app.yaml` | Спецификация App Platform (можно загрузить в DO) |
| `.env.example` | Список переменных окружения |

---

## Шаг 0. Локальная проверка перед деплоем

```bash
cd urban-city-backend

# Вариант A — без Docker (dev)
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
python3 smoke_test.py

# Вариант B — Docker (как на DigitalOcean)
docker compose up --build
# Swagger: http://localhost:8000/docs
# Health:  http://localhost:8000/health
curl http://localhost:8000/health
```

---

## Шаг 1. Залить код в GitHub

1. Создайте репозиторий, например `urban-city-backend`.
2. Запушьте код:

```bash
git init
git add .
git commit -m "Prepare backend for DigitalOcean deployment"
git remote add origin git@github.com:YOUR_ORG/urban-city-backend.git
git push -u origin main
```

3. В `.do/app.yaml` замените `YOUR_GITHUB_ORG/urban-city-backend` на свой репозиторий.

---

## Шаг 2. Сгенерировать JWT_SECRET

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

Сохраните строку — она понадобится в App Platform (≥ 32 символов).

---

## Шаг 3. Создать приложение в DigitalOcean

### Вариант A — через UI (проще)

1. Войдите в [cloud.digitalocean.com](https://cloud.digitalocean.com).
2. **Apps → Create App → GitHub** → выберите репозиторий `urban-city-backend`, ветку `main`.
3. DO обнаружит `Dockerfile` — тип компонента: **Web Service**.
4. Настройки сервиса:

| Параметр | Значение |
|---|---|
| Name | `api` |
| HTTP Port | `8080` |
| Instance size | **Basic XS** (1 GB RAM) — для пилота |
| Health Check Path | `/health` |
| Region | **Frankfurt (FRA1)** — ближе к KZ |

5. **Add Database → PostgreSQL 16**, план **Dev** (1 GB / 10 GB).
6. Привяжите БД к сервису — DO создаст переменную `DATABASE_URL`.

7. **Environment Variables** (App-Level или Component-Level):

| Key | Value | Тип |
|---|---|---|
| `ENV` | `production` | Plain |
| `PORT` | `8080` | Plain |
| `WEB_CONCURRENCY` | `2` | Plain |
| `USE_DB` | `1` | Plain |
| `RUN_MIGRATIONS` | `1` | Plain |
| `JWT_SECRET` | *(строка из шага 2)* | **Secret** |
| `CORS_ORIGINS` | `https://ВАШ-ФРОНТ.ondigitalocean.app` | Plain |
| `DATABASE_URL` | *(авто от Managed DB)* | Secret |

8. **Create Resources** → дождитесь деплоя (5–10 мин).

### Вариант B — через spec-файл

```bash
# doctl auth init   # один раз
doctl apps create --spec .do/app.yaml
```

Перед этим отредактируйте `.do/app.yaml`: репозиторий, `CORS_ORIGINS`, при необходимости регион.

---

## Шаг 4. Проверить деплой

После успешного деплоя DO выдаст URL вида `https://urban-city-backend-xxxxx.ondigitalocean.app`.

```bash
API=https://urban-city-backend-xxxxx.ondigitalocean.app

curl -s "$API/health" | python3 -m json.tool
# {"status":"ok","env":"production","database":"ok"}

curl -s "$API/api/v1/objects" | python3 -c "import sys,json; print(len(json.load(sys.stdin)), 'objects')"

open "$API/docs"
```

---

## Шаг 5. Привязать домен (опционально)

1. **Apps → ваше приложение → Settings → Domains**.
2. Добавьте, например, `api.urban-city.kz`.
3. В DNS регистратора создайте CNAME на `xxx.ondigitalocean.app`.
4. Обновите `CORS_ORIGINS` на фронте и бэке после деплоя фронта.

---

## Шаг 6. Подключить фронтенд

Когда фронт задеплоен (отдельное App Platform приложение или Static Site):

```env
# urban-city-frontend
NEXT_PUBLIC_USE_MOCK=false
NEXT_PUBLIC_API_BASE_URL=https://api.ВАШ-ДОМЕН/api/v1
```

На бэке обновите:

```env
CORS_ORIGINS=https://app.ВАШ-ДОМЕН
```

Перезапустите деплой бэка (Settings → Force Rebuild and Deploy).

---

## Переменные окружения — справочник

| Переменная | Обязательна в prod | Описание |
|---|---|---|
| `ENV` | да | `production` — включает проверку JWT и security-заголовки |
| `JWT_SECRET` | да | Случайная строка ≥ 32 символов |
| `CORS_ORIGINS` | да | URL фронта через запятую |
| `PORT` | да | `8080` (App Platform) |
| `DATABASE_URL` | рекомендуется | Строка от Managed PostgreSQL |
| `RUN_MIGRATIONS` | рекомендуется | `1` — применить Alembic при старте |
| `WEB_CONCURRENCY` | нет | Число gunicorn workers (по умолчанию `2`) |
| `USE_DB` | нет | `1` в production с БД |

---

## Деплой фронтенда в DO (кратко)

Отдельное приложение в App Platform:

| Параметр | Значение |
|---|---|
| Source | GitHub `urban-city-frontend` |
| Type | Web Service (Node.js) или Static Site |
| Build | `npm ci && npm run build` |
| Run | `npm start` (если SSR) |
| Instance | Basic XXS (512 MB) |
| Env | `NEXT_PUBLIC_USE_MOCK=false`, `NEXT_PUBLIC_API_BASE_URL=...` |

Фронт и бэк — **два отдельных компонента** в DO (или два App). Бэк уже готов принимать запросы.

---

## Стоимость (ориентир)

| Ресурс | План | ~$/мес |
|---|---|---|
| Backend App | Basic XS | 12 |
| Frontend App | Basic XXS | 5 |
| PostgreSQL | Dev 1 GB | 15 |
| **Итого** | | **~32** |

Для чистого демо без БД можно убрать PostgreSQL и `DATABASE_URL` (~$17/мес), но данные будут in-memory без персистентности.

---

## Troubleshooting

### Deploy failed: JWT_SECRET

```
RuntimeError: JWT_SECRET must be a random string of at least 32 characters in production
```

Задайте `JWT_SECRET` в Environment Variables (Secret), длина ≥ 32.

### Health check failing (503)

`DATABASE_URL` задан, но БД недоступна. Проверьте:
- Managed DB в том же регионе, что App;
- Trusted Sources: App добавлен в allowlist БД (DO делает автоматически при link);
- логи: `RUN_MIGRATIONS=1` — ошибка Alembic (права на `CREATE EXTENSION`).

### CORS error в браузере

`CORS_ORIGINS` должен **точно** совпадать с origin фронта (с `https://`, без слэша в конце).

| `DEMO_TODAY` | нет | Замороженная дата демо (`2026-07-02`) |

### Данные пропали после redeploy

Проверьте `USE_DB=1` и что `DATABASE_URL` задан. Без этого работает in-memory — данные сбрасываются.

### AppleDouble `._*` на exFAT

Перед `alembic upgrade head`:

```bash
find . -name '._*' -delete
```

---

## Полезные команды doctl

```bash
doctl apps list
doctl apps get <APP_ID>
doctl apps logs <APP_ID> --type run
doctl apps create-deployment <APP_ID>   # принудительный redeploy
```

---

## Чеклист перед показом заказчику

- [ ] `JWT_SECRET` задан (не дефолтный)
- [ ] `CORS_ORIGINS` указывает на фронт
- [ ] `/health` → `status: ok`
- [ ] `/docs` открывается
- [ ] `smoke_test.py` проходит локально
- [ ] Фронт: `NEXT_PUBLIC_USE_MOCK=false`
- [ ] Осознанно: auth в демо-режиме, данные in-memory
