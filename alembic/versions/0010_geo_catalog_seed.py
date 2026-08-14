"""Доливка полного каталога городов РК в geo_catalog_city (upsert).

Миграция 0009 создала таблицу и засеяла её тем, что было в app.geo_catalog на тот
момент (2 города). Здесь пере-сеиваем ПОЛНЫЙ актуальный список идемпотентно
(INSERT ... ON CONFLICT DO UPDATE), чтобы прод получил все 20 городов и оставался
в синхроне с app.geo_catalog при будущих доливках.

Revision ID: 0010
Revises: 0009
"""
from __future__ import annotations

import json

from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from app.geo_catalog import GEO_CATALOG_CITIES

    conn = op.get_bind()
    for city in GEO_CATALOG_CITIES:
        conn.execute(
            sa.text(
                "INSERT INTO geo_catalog_city (id, name, oblast, payload) "
                "VALUES (:id, :name, :oblast, CAST(:payload AS jsonb)) "
                "ON CONFLICT (id) DO UPDATE SET "
                "name = EXCLUDED.name, oblast = EXCLUDED.oblast, payload = EXCLUDED.payload"
            ),
            {
                "id": city["id"],
                "name": city["name"],
                "oblast": city.get("oblast"),
                "payload": json.dumps(city, ensure_ascii=False),
            },
        )


def downgrade() -> None:
    # Оставляем города республиканского значения и области — откат сида не размечаем
    # (данные-справочник, не схема). Явный no-op, чтобы не терять каталог случайно.
    pass
