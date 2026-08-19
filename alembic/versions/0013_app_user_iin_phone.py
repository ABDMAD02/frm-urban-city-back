"""app_user.iin + phone (nullable) + partial UNIQUE(region_id, iin).

ИИН — единственный надёжный идентификатор физлица в РК; один человек заводится
в городе один раз. Партиальный уникальный индекс не трогает существующие
аккаунты без ИИН (A-BE-1 ТЗ «владелец→бизнес и карта»).

Revision ID: 0013
Revises: 0012
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("app_user", sa.Column("iin", sa.Text(), nullable=True))
    op.add_column("app_user", sa.Column("phone", sa.Text(), nullable=True))
    op.create_index(
        "uq_app_user_region_iin",
        "app_user",
        ["region_id", "iin"],
        unique=True,
        postgresql_where=sa.text("iin IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_app_user_region_iin", table_name="app_user")
    op.drop_column("app_user", "phone")
    op.drop_column("app_user", "iin")
