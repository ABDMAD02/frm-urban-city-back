"""Флаг force-change: пользователь обязан сменить выданный temp-пароль при первом входе.

Revision ID: 0011
Revises: 0010
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # server_default=false → существующие аккаунты НЕ блокируются (флаг только у новых/сброшенных).
    op.add_column(
        "app_user",
        sa.Column(
            "password_change_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("app_user", "password_change_required")
