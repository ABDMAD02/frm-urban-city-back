"""Добавляет колонку code (публичный id API) на сущности с UUID-PK."""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

_CODE_TABLES = (
    "owner",
    "app_user",
    "city_object",
    "inspection",
    "prescription",
    "photo",
    "history_event",
    "object_version",
)


def upgrade() -> None:
    for table in _CODE_TABLES:
        op.add_column(table, sa.Column("code", sa.Text(), nullable=True))
        op.create_index(f"ix_{table}_code", table, ["code"], unique=True)
    # NOT NULL выставим после seed; nullable позволяет upgrade на пустой БД.


def downgrade() -> None:
    for table in reversed(_CODE_TABLES):
        op.drop_index(f"ix_{table}_code", table_name=table)
        op.drop_column(table, "code")
