"""Платформа: provisioning, geo catalog, UNIQUE geo names, map center.

Revision ID: 0009
Revises: 0008
"""
from __future__ import annotations

import json

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Новый статус региона: provisioning (гео ещё не готово).
    op.execute("ALTER TYPE region_status_enum ADD VALUE IF NOT EXISTS 'provisioning' BEFORE 'trial'")

    op.add_column("region", sa.Column("center_lat", sa.Double(), nullable=True))
    op.add_column("region", sa.Column("center_lng", sa.Double(), nullable=True))
    op.add_column("region", sa.Column("map_zoom", sa.Integer(), nullable=True))

    op.create_unique_constraint("uq_district_region_name", "district", ["region_id", "name"])
    op.create_unique_constraint("uq_microdistrict_region_name", "microdistrict", ["region_id", "name"])

    op.create_table(
        "geo_catalog_city",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("oblast", sa.Text(), nullable=True),
        sa.Column("payload", JSONB(), nullable=False),
    )

    # Seed catalog from app.geo_catalog (import at migration runtime).
    from app.geo_catalog import GEO_CATALOG_CITIES

    conn = op.get_bind()
    for city in GEO_CATALOG_CITIES:
        conn.execute(
            sa.text(
                "INSERT INTO geo_catalog_city (id, name, oblast, payload) "
                "VALUES (:id, :name, :oblast, CAST(:payload AS jsonb))"
            ),
            {
                "id": city["id"],
                "name": city["name"],
                "oblast": city.get("oblast"),
                "payload": json.dumps(city, ensure_ascii=False),
            },
        )


def downgrade() -> None:
    op.drop_table("geo_catalog_city")
    op.drop_constraint("uq_microdistrict_region_name", "microdistrict", type_="unique")
    op.drop_constraint("uq_district_region_name", "district", type_="unique")
    op.drop_column("region", "map_zoom")
    op.drop_column("region", "center_lng")
    op.drop_column("region", "center_lat")
    # PostgreSQL enum values cannot be removed safely; leave provisioning in type.
