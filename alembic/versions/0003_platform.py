"""Platform control-plane: regions, subscriptions, plans, audit + tenant region_id.

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-24
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from db.migration_helpers import create_enum_if_not_exists

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def _enum(name: str, *values: str) -> postgresql.ENUM:
    return postgresql.ENUM(*values, name=name, create_type=False)


region_status_enum = _enum("region_status_enum", "trial", "active", "suspended", "archived")
subscription_plan_enum = _enum("subscription_plan_enum", "trial", "standard", "pro")
subscription_status_enum = _enum("subscription_status_enum", "active", "grace", "expired")
locale_enum = _enum("locale_enum", "ru", "kk")
map_provider_enum = _enum("map_provider_enum", "2gis", "osm")
platform_audit_action_enum = _enum(
    "platform_audit_action_enum",
    "region_provisioned",
    "region_suspended",
    "region_activated",
    "region_archived",
    "subscription_renewed",
    "region_admin_issued",
    "region_admin_reissued",
)


def upgrade() -> None:
    # New enum value must be committed before use (PG restriction).
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE role_enum ADD VALUE IF NOT EXISTS 'platform_superadmin'")

    op.execute(
        create_enum_if_not_exists(
            "region_status_enum", "'trial','active','suspended','archived'"
        )
    )
    op.execute(
        create_enum_if_not_exists("subscription_plan_enum", "'trial','standard','pro'")
    )
    op.execute(
        create_enum_if_not_exists("subscription_status_enum", "'active','grace','expired'")
    )
    op.execute(create_enum_if_not_exists("locale_enum", "'ru','kk'"))
    op.execute(create_enum_if_not_exists("map_provider_enum", "'2gis','osm'"))
    op.execute(
        create_enum_if_not_exists(
            "platform_audit_action_enum",
            "'region_provisioned','region_suspended','region_activated','region_archived',"
            "'subscription_renewed','region_admin_issued','region_admin_reissued'",
        )
    )

    op.create_table(
        "region",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("code", sa.Text(), nullable=False, unique=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("status", region_status_enum, nullable=False),
        sa.Column("timezone", sa.Text(), nullable=False, server_default="Asia/Oral"),
        sa.Column("locale", locale_enum, nullable=False, server_default="ru"),
        sa.Column("map_provider", map_provider_enum, nullable=False, server_default="2gis"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.create_table(
        "plan",
        sa.Column("id", subscription_plan_enum, primary_key=True),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("max_users", sa.Integer(), nullable=False),
        sa.Column("max_objects", sa.Integer(), nullable=False),
        sa.Column("price_hint", sa.Text(), nullable=False, server_default=""),
    )

    op.create_table(
        "subscription",
        sa.Column("region_id", sa.Text(), sa.ForeignKey("region.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("plan", subscription_plan_enum, nullable=False),
        sa.Column("status", subscription_status_enum, nullable=False, server_default="active"),
        sa.Column("max_users", sa.Integer(), nullable=False),
        sa.Column("max_objects", sa.Integer(), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_until", sa.Date(), nullable=False),
    )

    op.create_table(
        "platform_audit",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("region_id", sa.Text(), sa.ForeignKey("region.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("action", platform_audit_action_enum, nullable=False),
        sa.Column("detail", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_platform_audit_region_id", "platform_audit", ["region_id"])
    op.create_index("ix_platform_audit_at", "platform_audit", ["at"])

    # Plan catalog only — no demo region/users/objects on a fresh DB.
    op.execute(
        """
        INSERT INTO plan (id, label, max_users, max_objects, price_hint) VALUES
          ('trial', 'Trial', 10, 50, 'Бесплатно'),
          ('standard', 'Standard', 50, 500, 'По запросу'),
          ('pro', 'Pro', 200, 5000, 'По запросу')
        ON CONFLICT (id) DO NOTHING
        """
    )
    # Default region only when upgrading a DB that already has tenant rows to backfill.
    op.execute(
        """
        INSERT INTO region (id, code, name, status, timezone, locale, map_provider)
        SELECT 'uralsk', 'uralsk', 'Уральск', 'active', 'Asia/Oral', 'ru', '2gis'
        WHERE EXISTS (SELECT 1 FROM district LIMIT 1)
           OR EXISTS (SELECT 1 FROM microdistrict LIMIT 1)
           OR EXISTS (SELECT 1 FROM owner LIMIT 1)
           OR EXISTS (SELECT 1 FROM object_type LIMIT 1)
           OR EXISTS (SELECT 1 FROM city_object LIMIT 1)
           OR EXISTS (
                SELECT 1 FROM app_user
                WHERE role::text <> 'platform_superadmin'
                LIMIT 1
           )
        ON CONFLICT (id) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO subscription (region_id, plan, status, max_users, max_objects, valid_from, valid_until)
        SELECT 'uralsk', 'standard', 'active', 50, 500,
               CURRENT_DATE, CURRENT_DATE + INTERVAL '1 year'
        WHERE EXISTS (SELECT 1 FROM region WHERE id = 'uralsk')
        ON CONFLICT (region_id) DO NOTHING
        """
    )

    op.add_column("district", sa.Column("region_id", sa.Text(), nullable=True))
    op.add_column("microdistrict", sa.Column("region_id", sa.Text(), nullable=True))
    op.add_column("owner", sa.Column("region_id", sa.Text(), nullable=True))
    op.add_column("object_type", sa.Column("region_id", sa.Text(), nullable=True))
    op.add_column("city_object", sa.Column("region_id", sa.Text(), nullable=True))
    op.add_column("app_user", sa.Column("region_id", sa.Text(), nullable=True))
    op.add_column("app_user", sa.Column("email", sa.Text(), nullable=True))

    op.execute("UPDATE district SET region_id = 'uralsk' WHERE region_id IS NULL")
    op.execute("UPDATE microdistrict SET region_id = 'uralsk' WHERE region_id IS NULL")
    op.execute("UPDATE owner SET region_id = 'uralsk' WHERE region_id IS NULL")
    op.execute("UPDATE object_type SET region_id = 'uralsk' WHERE region_id IS NULL")
    op.execute("UPDATE city_object SET region_id = 'uralsk' WHERE region_id IS NULL")
    op.execute(
        "UPDATE app_user SET region_id = 'uralsk' "
        "WHERE role::text <> 'platform_superadmin' AND region_id IS NULL"
    )

    # Empty tenant tables stay empty; NOT NULL is fine with zero rows.
    # If rows exist without a region (should not happen after conditional insert), fail loudly.
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (
            SELECT 1 FROM district WHERE region_id IS NULL
            UNION ALL SELECT 1 FROM microdistrict WHERE region_id IS NULL
            UNION ALL SELECT 1 FROM owner WHERE region_id IS NULL
            UNION ALL SELECT 1 FROM object_type WHERE region_id IS NULL
            UNION ALL SELECT 1 FROM city_object WHERE region_id IS NULL
          ) THEN
            RAISE EXCEPTION 'region backfill failed: tenant rows without region_id';
          END IF;
        END $$;
        """
    )

    op.alter_column("district", "region_id", nullable=False)
    op.alter_column("microdistrict", "region_id", nullable=False)
    op.alter_column("owner", "region_id", nullable=False)
    op.alter_column("object_type", "region_id", nullable=False)
    op.alter_column("city_object", "region_id", nullable=False)

    op.create_foreign_key("fk_district_region", "district", "region", ["region_id"], ["id"], ondelete="CASCADE")
    op.create_foreign_key("fk_microdistrict_region", "microdistrict", "region", ["region_id"], ["id"], ondelete="CASCADE")
    op.create_foreign_key("fk_owner_region", "owner", "region", ["region_id"], ["id"], ondelete="CASCADE")
    op.create_foreign_key("fk_object_type_region", "object_type", "region", ["region_id"], ["id"], ondelete="CASCADE")
    op.create_foreign_key("fk_city_object_region", "city_object", "region", ["region_id"], ["id"], ondelete="CASCADE")
    op.create_foreign_key("fk_app_user_region", "app_user", "region", ["region_id"], ["id"], ondelete="SET NULL")

    op.create_index("ix_district_region_id", "district", ["region_id"])
    op.create_index("ix_microdistrict_region_id", "microdistrict", ["region_id"])
    op.create_index("ix_owner_region_id", "owner", ["region_id"])
    op.create_index("ix_object_type_region_id", "object_type", ["region_id"])
    op.create_index("ix_city_object_region_id", "city_object", ["region_id"])
    op.create_index("ix_app_user_region_id", "app_user", ["region_id"])
    op.create_index("ix_app_user_email", "app_user", ["email"], unique=True)

    # Drop FK city_object.type -> object_type.name before dropping unique on name.
    op.drop_constraint("city_object_type_fkey", "city_object", type_="foreignkey")
    op.drop_constraint("object_type_name_key", "object_type", type_="unique")
    op.create_unique_constraint("uq_object_type_region_name", "object_type", ["region_id", "name"])

    # Platform superadmin is optional — created by BOOTSTRAP_PLATFORM=1 at startup, not by migration.


def downgrade() -> None:
    op.execute("DELETE FROM app_user WHERE role = 'platform_superadmin'")
    op.drop_constraint("uq_object_type_region_name", "object_type", type_="unique")
    op.create_foreign_key(
        "city_object_type_fkey",
        "city_object",
        "object_type",
        ["type"],
        ["name"],
        onupdate="CASCADE",
        ondelete="RESTRICT",
    )
    op.create_unique_constraint("object_type_name_key", "object_type", ["name"])

    for table, fk in (
        ("district", "fk_district_region"),
        ("microdistrict", "fk_microdistrict_region"),
        ("owner", "fk_owner_region"),
        ("object_type", "fk_object_type_region"),
        ("city_object", "fk_city_object_region"),
        ("app_user", "fk_app_user_region"),
    ):
        op.drop_constraint(fk, table, type_="foreignkey")

    for table, col in (
        ("district", "region_id"),
        ("microdistrict", "region_id"),
        ("owner", "region_id"),
        ("object_type", "region_id"),
        ("city_object", "region_id"),
        ("app_user", "region_id"),
        ("app_user", "email"),
    ):
        op.drop_column(table, col)

    op.drop_table("platform_audit")
    op.drop_table("subscription")
    op.drop_table("plan")
    op.drop_table("region")

    for name in (
        "platform_audit_action_enum",
        "map_provider_enum",
        "locale_enum",
        "subscription_status_enum",
        "subscription_plan_enum",
        "region_status_enum",
    ):
        op.execute(f"DROP TYPE IF EXISTS {name}")
