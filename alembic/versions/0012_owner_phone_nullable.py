"""owner.phone → nullable: импортированные из госреестра (data.egov.kz) бизнесы без телефона.

Revision ID: 0012
Revises: 0011
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("owner", "phone", existing_type=sa.Text(), nullable=True)


def downgrade() -> None:
    # Пустые телефоны заполняем '', иначе NOT NULL не наложить.
    op.execute("UPDATE owner SET phone = '' WHERE phone IS NULL")
    op.alter_column("owner", "phone", existing_type=sa.Text(), nullable=False)
