"""Owner.owner_user_id: account (role=owner) may own many businesses (ТОО/ИП).

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-28
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "owner",
        sa.Column("owner_user_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_owner_owner_user",
        "owner",
        "app_user",
        ["owner_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_owner_owner_user_id", "owner", ["owner_user_id"])

    # Backfill from legacy AppUser.owner_id (1:1) → Owner.owner_user_id (1:N-ready).
    op.execute(
        """
        UPDATE owner o
        SET owner_user_id = u.id
        FROM app_user u
        WHERE u.owner_id = o.id
          AND u.role::text = 'owner'
          AND o.owner_user_id IS NULL
        """
    )

    # Drop 1:1 constraints so one account can own many Owner rows.
    op.execute("DROP INDEX IF EXISTS uq_user_owner")
    op.drop_constraint("owner_link", "app_user", type_="check")


def downgrade() -> None:
    op.create_check_constraint(
        "owner_link",
        "app_user",
        "role <> 'owner' OR owner_id IS NOT NULL",
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_user_owner ON app_user(owner_id) WHERE owner_id IS NOT NULL"
    )
    # Best-effort reverse backfill (first owner only).
    op.execute(
        """
        UPDATE app_user u
        SET owner_id = sub.owner_id
        FROM (
          SELECT DISTINCT ON (owner_user_id) owner_user_id, id AS owner_id
          FROM owner
          WHERE owner_user_id IS NOT NULL
          ORDER BY owner_user_id, id
        ) sub
        WHERE u.id = sub.owner_user_id
          AND u.role::text = 'owner'
          AND u.owner_id IS NULL
        """
    )
    op.drop_index("ix_owner_owner_user_id", table_name="owner")
    op.drop_constraint("fk_owner_owner_user", "owner", type_="foreignkey")
    op.drop_column("owner", "owner_user_id")
