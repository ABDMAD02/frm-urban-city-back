"""Constraints & indexes: partial UNIQUE(region_id, bin) per city + missing FK indexes.

Revision ID: 0006
Revises: 0005

P1-ограничения БД:
  1. БИН уникален в пределах города (партиальный UNIQUE, т.к. owner.bin nullable для
     физлиц без ИИН) — раньше уникальности не было вовсе.
  2. Индексы на внешних ключах, которых физически не было:
       - city_object.street_id      (FK на street; добавлен в 0005 без индекса)
       - app_user.owner_id          (индекс был неявным через uq_user_owner, дропнут в 0004)
       - street.district_id         (FK на district; в 0005 без индекса)
       - street.microdistrict_id    (FK на microdistrict; в 0005 без индекса)
       - inspection.inspector_id    (FK на app_user; без индекса с 0001)
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. БИН уникален per-city; партиальный, т.к. bin nullable для физлиц без ИИН.
    op.create_index(
        "uq_owner_region_bin",
        "owner",
        ["region_id", "bin"],
        unique=True,
        postgresql_where=sa.text("bin IS NOT NULL"),
    )

    # 2. Недостающие индексы на внешних ключах.
    op.create_index("ix_city_object_street_id", "city_object", ["street_id"])
    op.create_index("ix_app_user_owner_id", "app_user", ["owner_id"])
    op.create_index("ix_street_district_id", "street", ["district_id"])
    op.create_index("ix_street_microdistrict_id", "street", ["microdistrict_id"])
    op.create_index("ix_inspection_inspector_id", "inspection", ["inspector_id"])


def downgrade() -> None:
    op.drop_index("ix_inspection_inspector_id", table_name="inspection")
    op.drop_index("ix_street_microdistrict_id", table_name="street")
    op.drop_index("ix_street_district_id", table_name="street")
    op.drop_index("ix_app_user_owner_id", table_name="app_user")
    op.drop_index("ix_city_object_street_id", table_name="city_object")
    op.drop_index("uq_owner_region_bin", table_name="owner")
