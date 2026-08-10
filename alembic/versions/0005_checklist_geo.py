"""Checklist template + flexible geography (streets, region geo config).

Revision ID: 0005
Revises: 0004
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Region geo settings ───────────────────────────────────────
    op.add_column("region", sa.Column("city_type", sa.Text(), nullable=True))
    op.add_column("region", sa.Column("oblast", sa.Text(), nullable=True))
    op.add_column(
        "region",
        sa.Column("has_districts", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.add_column(
        "region",
        sa.Column(
            "has_microdistricts", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
    )
    op.add_column(
        "region",
        sa.Column("has_streets", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.add_column(
        "region",
        sa.Column(
            "address_schema",
            sa.Text(),
            nullable=False,
            server_default="microdistrict,street,house",
        ),
    )
    op.execute(
        """
        UPDATE region SET
          city_type = COALESCE(city_type, 'city'),
          oblast = COALESCE(oblast, 'ЗКО'),
          address_schema = COALESCE(NULLIF(address_schema, ''), 'microdistrict,street,house')
        WHERE id = 'uralsk'
        """
    )

    # ── Microdistrict.district_id nullable ────────────────────────
    op.alter_column("microdistrict", "district_id", existing_type=sa.Text(), nullable=True)

    # ── Street ────────────────────────────────────────────────────
    op.create_table(
        "street",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("code", sa.Text(), unique=True),
        sa.Column("region_id", sa.Text(), sa.ForeignKey("region.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("district_id", sa.Text(), sa.ForeignKey("district.id", ondelete="SET NULL"), nullable=True),
        sa.Column(
            "microdistrict_id",
            sa.Text(),
            sa.ForeignKey("microdistrict.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_street_region_id", "street", ["region_id"])

    # ── CityObject address parts ──────────────────────────────────
    op.add_column(
        "city_object",
        sa.Column("street_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("street.id", ondelete="SET NULL")),
    )
    op.add_column("city_object", sa.Column("house", sa.Text(), nullable=True))
    op.add_column("city_object", sa.Column("apartment", sa.Text(), nullable=True))

    # ── Checklist template ────────────────────────────────────────
    op.create_table(
        "checklist_template",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("region_id", sa.Text(), sa.ForeignKey("region.id", ondelete="CASCADE"), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("title_ru", sa.Text(), nullable=False),
        sa.Column("title_kz", sa.Text(), nullable=False, server_default=""),
        sa.Column("category", sa.Text(), nullable=False, server_default=""),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_visible", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.UniqueConstraint("region_id", "key", name="uq_checklist_template_region_key"),
    )
    op.create_index("ix_checklist_template_region_id", "checklist_template", ["region_id"])

    # Seed Uralsk checklist (6 items from TZ).
    # Регион 'uralsk' создаётся сидом (db/seed.py), который идёт ПОСЛЕ миграций,
    # поэтому на пустой базе его здесь ещё нет. Безусловный INSERT ронял миграцию
    # с ForeignKeyViolation. Вставляем только если регион уже существует;
    # для чистой базы чек-лист засевает db/seed.py._ensure_platform_bootstrap.
    op.execute(
        """
        INSERT INTO checklist_template (id, region_id, key, title_ru, title_kz, category, sort_order, is_visible)
        SELECT gen_random_uuid(), 'uralsk', v.key, v.title_ru, v.title_kz, v.category, v.sort_order, true
        FROM (VALUES
          ('facade', 'Фасад', 'Фасад', 'building', 1),
          ('signboard', 'Вывеска', 'Маңдайша', 'signage', 2),
          ('ads', 'Реклама', 'Жарнама', 'advertising', 3),
          ('banners', 'Баннеры', 'Баннерлер', 'advertising', 4),
          ('lighting', 'Освещение', 'Жарықтандыру', 'lighting', 5),
          ('materials', 'Материалы', 'Материалдар', 'materials', 6)
        ) AS v(key, title_ru, title_kz, category, sort_order)
        WHERE EXISTS (SELECT 1 FROM region WHERE id = 'uralsk')
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index("ix_checklist_template_region_id", table_name="checklist_template")
    op.drop_table("checklist_template")
    op.drop_column("city_object", "apartment")
    op.drop_column("city_object", "house")
    op.drop_column("city_object", "street_id")
    op.drop_index("ix_street_region_id", table_name="street")
    op.drop_table("street")
    op.alter_column("microdistrict", "district_id", existing_type=sa.Text(), nullable=False)
    op.drop_column("region", "address_schema")
    op.drop_column("region", "has_streets")
    op.drop_column("region", "has_microdistricts")
    op.drop_column("region", "has_districts")
    op.drop_column("region", "oblast")
    op.drop_column("region", "city_type")
