# Слой БД Urban City (SQLAlchemy 2.0 + Alembic)

Персистентная реализация хранилища на **PostgreSQL 15+**. Это **параллельный** слой:
in-memory сервер (`app/store.py` + роутеры) продолжает работать без изменений. Переключение
на БД — опциональный шаг (см. ниже), сама выкладка миграции сервер не ломает.

Источник истины по схеме — `02_Спецификация/05_ER_модель.md` и `app/models.py` / `app/enums.py`.

## Состав

| Файл | Назначение |
|---|---|
| `db/base.py` | Declarative `Base`, `engine`, `SessionLocal`, зависимость `get_session`. URL из `DATABASE_URL`. |
| `db/enums.py` | Python-энумы = зеркало `app/enums.py`; имена нативных ENUM-типов PG. |
| `db/models.py` | Все ORM-модели (SQLAlchemy 2.0 `Mapped`/`mapped_column`). |
| `alembic/versions/0001_initial.py` | Первая миграция: расширения, ENUM-типы, таблицы, индексы, триггеры. |
| `alembic.ini`, `alembic/env.py` | Конфигурация Alembic (URL берётся из окружения). |

## Таблицы (16)

`district`, `microdistrict`, `owner`, `object_type`, `app_user`, `user_microdistrict` (M:N),
`city_object`, `inspection`, `checklist_item`, `prescription`, `photo`, `history_event`,
`object_version`, `notification`, `refresh_token`, `idempotency_key`.

Ключевые инварианты на уровне БД: частичный UNIQUE `1 предписание на проверку`
(`uq_prescription_inspection`), `1 аккаунт на собственника` (`uq_user_owner`),
append-only история (триггер), авто-`updated_at` (триггер), синхронизация денорм. `district_id`
(триггер), запрет физического DELETE объекта (мягкое удаление). Колонка `version` для
оптимистичной блокировки — на `city_object`, `prescription`, `app_user`, `owner`.

## 1. Переменная окружения `DATABASE_URL`

```bash
# Формат: postgresql+psycopg://<user>:<pass>@<host>:<port>/<db>
export DATABASE_URL="postgresql+psycopg://urban:urban@localhost:5432/urban_city"
```

Если переменная не задана — используется дефолт из `db/base.py`
(`postgresql+psycopg://urban:urban@localhost:5432/urban_city`).
Схема `postgres://...` (Railway/Heroku) нормализуется автоматически в `postgresql+psycopg://`.

Поднять локальный Postgres (пример):

```bash
docker run --name urban-pg -e POSTGRES_USER=urban -e POSTGRES_PASSWORD=urban \
  -e POSTGRES_DB=urban_city -p 5432:5432 -d postgres:16
```

## 2. Установка и применение миграций

```bash
pip install -r requirements.txt          # добавлены SQLAlchemy, alembic, psycopg

# применить все миграции (создаст расширения, enum-типы, таблицы, индексы, триггеры)
alembic upgrade head

# откатить последнюю
alembic downgrade -1

# сгенерировать новую ревизию после правки db/models.py
alembic revision --autogenerate -m "описание"
```

Все команды запускать из каталога бэкенда
(`04_Backend_FastAPI/urban-city-backend/`), где лежит `alembic.ini`.

> Расширения `pgcrypto`, `pg_trgm`, `btree_gin` создаются миграцией через
> `CREATE EXTENSION IF NOT EXISTS`. На управляемом Postgres нужны права суперюзера/владельца БД.

> Troubleshooting (exFAT/сетевые тома): macOS создаёт AppleDouble-файлы `._*`
> (бинарные, с null-байтами). Alembic сканирует `alembic/versions/*.py` и падает на
> `._0001_initial.py` с `source code string cannot contain null bytes`. Удалить перед запуском:
> `find . -name '._*' -delete`. На Linux/в проде их нет.

## 3. Переключение сервера с in-memory на БД (заглушка)

Сейчас роутеры ходят в `app/store.py` (in-memory). Миграция на БД — отдельный слой репозитория,
который **не входит** в эту задачу; ниже — эскиз интеграции, чтобы не трогать существующий код
до готовности репозиториев:

```python
# app/deps.py (новый файл — черновик)
from db.base import get_session          # сессия на запрос

# В роутере вместо обращения к store:
#   from fastapi import Depends
#   from sqlalchemy.orm import Session
#   from db import models
#
#   @router.get("/objects")
#   def list_objects(session: Session = Depends(get_session)):
#       return session.query(models.CityObject).all()
```

Порядок перехода (рекомендация):
1. написать репозитории (`db/repositories/*.py`), повторяющие сигнатуры методов `store.py`;
2. ввести флаг окружения `USE_DB=1` и в `app/*` выбирать реализацию (in-memory ↔ БД);
3. перенести сид-данные из `store.py` в скрипт `db/seed.py` (INSERT через ORM);
4. по готовности удалить in-memory ветку.

До выполнения этих шагов сервер работает как прежде — слой `db/` подключается только
командами Alembic и не импортируется приложением.
