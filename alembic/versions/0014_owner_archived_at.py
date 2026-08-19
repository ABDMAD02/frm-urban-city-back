"""owner.archived_at — мягкое архивирование бизнеса (A-BE-6).

Архивные бизнесы не попадают в GET /owners; удаление запрещено при наличии
не архивных объектов.

Revision ID: 0014
Revises: 0013
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("owner", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("owner", "archived_at")
