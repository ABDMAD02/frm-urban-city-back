# Urban City — Backend (FastAPI)

Рабочий **скелет** серверной части по контракту `../spec/openapi.yaml`.
Пилот — г. Уральск. Хранилище — **PostgreSQL** (production) или in-memory (локальный dev без `DATABASE_URL`).

## Что уже работает

- Все **39 методов** контракта (18 «ядро» + 21 «добавить»), сгруппированные по роутерам.
- **FSM объекта** валидируется на сервере (недопустимый переход → `409`).
- Проверка с замечаниями **авто-создаёт предписание** и ведёт объект `has_remarks → prescription_issued`.
- Повторная проверка пересчитывает статус (`fixed → violation_fixed`, иначе продление).
- **Фото обязательны** при проверке (иначе `400`).
- Аутентификация JWT (`/auth/v2/login`, `/auth/v2/refresh`), профиль `/auth/me`.
- Серверная аналитика (`/analytics/summary`, `/by-district`, `/status-distribution`).
- Роуты смонтированы под `/api/v1` (мобилка) **и** `/api` (текущий веб).

## Запуск

```bash
cd urban-city-backend
python3 -m venv .venv && source .venv/bin/activate   # если venv недоступен — можно ставить в текущее окружение
pip install -r requirements.txt
# На Python < 3.10 дополнительно: pip install eval_type_backport
uvicorn app.main:app --reload
```

Открыть:
- **Swagger UI:** http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc
- Схема: http://localhost:8000/openapi.json

## Подключить фронт к этому серверу

В `urban-city-frontend/.env.local`:
```
NEXT_PUBLIC_USE_MOCK=false
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api/v1
```
(в скелете CORS разрешает `localhost:3000/3001`; вход по куке не требуется — get_current_user в демо мягкий).

## Тест

```bash
python3 smoke_test.py     # 21 проверка: чтения, FSM, проверка+предписание, повторная проверка, auth, users
```

## Деплой (DigitalOcean)

Production-образ и инструкция: **[DEPLOY.md](./DEPLOY.md)**.

```bash
# Локально «как на проде»
docker compose up --build
```

Переменные окружения — см. `.env.example`. В production обязательны `ENV=production`, `JWT_SECRET` (≥32 символов), `CORS_ORIGINS`.

## Структура

```
app/
├── main.py         # FastAPI, CORS, монтирование роутов на /api/v1 и /api
├── config.py       # префиксы, JWT, CORS
├── enums.py        # роли, статусы, типы (зеркало domain/entities.ts)
├── models.py       # Pydantic-схемы (сущности + тела запросов/ответов)
├── fsm.py          # ALLOWED_TRANSITIONS + can_transition + чек-лист
├── security.py     # JWT, get_current_user
├── store.py        # in-memory сид-данные (dev без БД)
├── deps.py         # USE_DB + get_store()
├── storage/        # MemoryStore (обёртка store.py)
└── routers/
    ├── auth.py            # вход, refresh, me, смена пароля
    ├── objects.py         # объекты, поиск, геокодинг
    ├── inspections.py     # проверки, повторные проверки (бизнес-логика)
    ├── prescriptions.py   # предписания, отправка по email
    ├── users.py           # пользователи, логин+временный пароль
    ├── reference.py       # собственники, справочники, фото, история, версии
    ├── analytics.py       # KPI и разрезы
    └── misc.py            # аудит, уведомления

db/
├── repository.py   # DbStore — PostgreSQL
├── seed.py         # загрузка сид-данных
├── mappers.py      # ORM ↔ Pydantic
└── models.py       # SQLAlchemy ORM
```

## Что доделать до прода (осознанные заглушки скелета)

- Реальная проверка паролей (хэш bcrypt/argon2) — сейчас login принимает любой пароль.
- Хранилище файлов для фото (S3/диск) — сейчас `POST /photos` не сохраняет файл.
- Реальная отправка email в `/prescriptions/{id}/send` (SMTP).
- Реальный обратный геокодер в `/geocode/reverse`.
- Жёсткий RBAC-скоуп на всех эндпоинтах (сейчас скоуп применён к `/objects`, get_current_user в демо мягкий).
- Крон перевода предписаний `open → overdue` по сроку.

## PostgreSQL

| `USE_DB` | Поведение |
|---|---|
| `0` | In-memory (`app/store.py`) |
| `1` | PostgreSQL через `db/repository.py` |
| `auto` (default) | PostgreSQL если `DATABASE_URL` задан и `ENV=production` |

```bash
# Локально с БД
docker compose up --build   # USE_DB=1, миграции + seed автоматически
```
