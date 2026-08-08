"""Полностью убрать подписки и тарифы (платформа отдаётся бесплатно).

Revision ID: 0008
Revises: 0007
"""
from __future__ import annotations

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("subscription")
    op.drop_table("plan")
    # Нативные ENUM-типы больше не используются.
    op.execute("DROP TYPE IF EXISTS subscription_status_enum")
    op.execute("DROP TYPE IF EXISTS subscription_plan_enum")


def downgrade() -> None:
    # Откат не поддерживается: подписки удалены осознанно как продуктовое решение.
    # Восстановление — из миграции 0003 (create) при необходимости, вручную.
    raise NotImplementedError("subscriptions removed intentionally; no downgrade")
