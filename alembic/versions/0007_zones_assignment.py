"""Зоны урбаниста по улицам + переопределение ответственного за объект.

Revision ID: 0007
Revises: 0006
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A. Зоны-улицы урбаниста (N:M), по образцу user_microdistrict.
    op.create_table(
        "user_street",
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("street_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("street.id", ondelete="CASCADE"), primary_key=True),
    )
    op.create_index("ix_user_street_street_id", "user_street", ["street_id"])

    # B. Переопределение ответственного за объект. NULL = «по зоне».
    # SET NULL: при удалении урбаниста объект возвращается в зону (BR-3), не теряется.
    op.add_column(
        "city_object",
        sa.Column(
            "assigned_urbanist_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("app_user.id", ondelete="SET NULL"), nullable=True,
        ),
    )
    op.create_index(
        "ix_city_object_assigned_urbanist_id", "city_object", ["assigned_urbanist_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_city_object_assigned_urbanist_id", table_name="city_object")
    op.drop_column("city_object", "assigned_urbanist_id")
    op.drop_index("ix_user_street_street_id", table_name="user_street")
    op.drop_table("user_street")
