"""initial schema: enum-типы, таблицы, индексы, триггеры Urban City.

Реализует физическую модель из ``02_Спецификация/05_ER_модель.md`` (§6-9)
плюс служебные таблицы ``refresh_token`` и ``idempotency_key`` (Стандарты API §2-3)
и колонку ``version`` на изменяемых сущностях.

Revision ID: 0001
Revises:
Create Date: 2026-07-19
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from db.migration_helpers import create_enum_if_not_exists

# идентификаторы ревизии
revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


# ── Определения нативных ENUM-типов PG (create_type=False: создаём вручную ниже) ──
def _enum(name: str, *values: str) -> postgresql.ENUM:
    return postgresql.ENUM(*values, name=name, create_type=False)


role_enum = _enum("role_enum", "urbanist", "owner", "region_admin")
account_status_enum = _enum("account_status_enum", "active", "blocked")
object_status_enum = _enum(
    "object_status_enum",
    "new", "not_inspected", "compliant", "has_remarks", "prescription_issued",
    "awaiting_reinspection", "violation_fixed", "closed", "archived",
)
inspection_result_enum = _enum("inspection_result_enum", "compliant", "has_remarks")
prescription_status_enum = _enum("prescription_status_enum", "open", "overdue", "fixed", "closed")
legal_form_enum = _enum("legal_form_enum", "ИП", "ТОО", "Физлицо", "Госорган")
checklist_value_enum = _enum("checklist_value_enum", "ok", "issue", "na")
photo_kind_enum = _enum("photo_kind_enum", "before", "after", "general")
history_type_enum = _enum(
    "history_type_enum",
    "object_created", "card_updated", "owner_changed", "inspection_done",
    "prescription_issued", "photos_uploaded", "violation_fixed", "reinspection",
    "status_changed", "archived",
)


def upgrade() -> None:
    # ── (0) Расширения ────────────────────────────────────────────
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto;")   # gen_random_uuid()
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")    # триграммный поиск
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gin;")  # составные GIN (опционально)

    # ── (1) ENUM-типы (зеркало app/enums.py) ──────────────────────
    op.execute(create_enum_if_not_exists("role_enum", "'urbanist','owner','region_admin'"))
    op.execute(create_enum_if_not_exists("account_status_enum", "'active','blocked'"))
    op.execute(
        create_enum_if_not_exists(
            "object_status_enum",
            "'new','not_inspected','compliant','has_remarks','prescription_issued',"
            "'awaiting_reinspection','violation_fixed','closed','archived'",
        )
    )
    op.execute(
        create_enum_if_not_exists("inspection_result_enum", "'compliant','has_remarks'")
    )
    op.execute(
        create_enum_if_not_exists(
            "prescription_status_enum", "'open','overdue','fixed','closed'"
        )
    )
    op.execute(
        create_enum_if_not_exists("legal_form_enum", "'ИП','ТОО','Физлицо','Госорган'")
    )
    op.execute(create_enum_if_not_exists("checklist_value_enum", "'ok','issue','na'"))
    op.execute(create_enum_if_not_exists("photo_kind_enum", "'before','after','general'"))
    op.execute(
        create_enum_if_not_exists(
            "history_type_enum",
            "'object_created','card_updated','owner_changed','inspection_done',"
            "'prescription_issued','photos_uploaded','violation_fixed','reinspection',"
            "'status_changed','archived'",
        )
    )

    # ── (2) Справочники географии ─────────────────────────────────
    op.create_table(
        "district",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
    )
    op.create_table(
        "microdistrict",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "district_id", sa.Text(),
            sa.ForeignKey("district.id", ondelete="RESTRICT"), nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
    )

    # ── (3) Собственники ──────────────────────────────────────────
    op.create_table(
        "owner",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("legal_form", legal_form_enum, nullable=False),
        sa.Column("bin", sa.Text()),
        sa.Column("phone", sa.Text(), nullable=False),
        sa.Column("email", sa.Text()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.CheckConstraint(r"bin IS NULL OR bin ~ '^[0-9]{12}$'", name="bin_format"),
        sa.CheckConstraint(
            r"email IS NULL OR email ~* '^[^@\s]+@[^@\s]+\.[^@\s]+$'", name="email_format"
        ),
    )

    # ── (4) Справочник типов объектов ─────────────────────────────
    op.create_table(
        "object_type",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.Text(), nullable=False, unique=True),
        sa.Column("category", sa.Text()),
    )

    # ── (5) Пользователи ──────────────────────────────────────────
    op.create_table(
        "app_user",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("role", role_enum, nullable=False),
        sa.Column("position", sa.Text(), nullable=False),
        sa.Column("login", sa.Text(), unique=True),
        sa.Column("password_hash", sa.Text()),
        sa.Column("status", account_status_enum, nullable=False, server_default="active"),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("owner.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.CheckConstraint("role <> 'owner' OR owner_id IS NOT NULL", name="owner_link"),
    )
    # один аккаунт на одного собственника (частичный UNIQUE)
    op.execute(
        "CREATE UNIQUE INDEX uq_user_owner ON app_user(owner_id) WHERE owner_id IS NOT NULL;"
    )

    # ── (6) N:M закрепление за микрорайонами ──────────────────────
    op.create_table(
        "user_microdistrict",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("microdistrict_id", sa.Text(), sa.ForeignKey("microdistrict.id", ondelete="CASCADE"), primary_key=True),
    )

    # ── (7) Объекты города (корневой агрегат) ─────────────────────
    op.create_table(
        "city_object",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "type", sa.Text(),
            sa.ForeignKey("object_type.name", onupdate="CASCADE", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("category", sa.Text()),
        sa.Column("address", sa.Text()),
        sa.Column("lat", sa.Double(), nullable=False),
        sa.Column("lng", sa.Double(), nullable=False),
        sa.Column("district_id", sa.Text(), sa.ForeignKey("district.id", ondelete="RESTRICT")),
        sa.Column("microdistrict_id", sa.Text(), sa.ForeignKey("microdistrict.id", ondelete="RESTRICT")),
        sa.Column("street", sa.Text()),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("owner.id", ondelete="RESTRICT")),
        sa.Column("status", object_status_enum, nullable=False, server_default="new"),
        sa.Column("responsible", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.CheckConstraint("lat BETWEEN -90 AND 90", name="lat_range"),
        sa.CheckConstraint("lng BETWEEN -180 AND 180", name="lng_range"),
    )

    # ── (8) Проверки ──────────────────────────────────────────────
    op.create_table(
        "inspection",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("object_id", sa.Uuid(), sa.ForeignKey("city_object.id", ondelete="CASCADE"), nullable=False),
        sa.Column("inspector_id", sa.Uuid(), sa.ForeignKey("app_user.id", ondelete="SET NULL")),
        sa.Column("inspector", sa.Text(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("result", inspection_result_enum, nullable=False),
        sa.Column("comment", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # ── (9) Пункты чек-листа ──────────────────────────────────────
    op.create_table(
        "checklist_item",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("inspection_id", sa.Uuid(), sa.ForeignKey("inspection.id", ondelete="CASCADE"), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("value", checklist_value_enum, nullable=False),
        sa.Column("comment", sa.Text()),
        sa.UniqueConstraint("inspection_id", "key", name="uq_checklist_key"),
    )

    # ── (10) Предписания ──────────────────────────────────────────
    op.create_table(
        "prescription",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("object_id", sa.Uuid(), sa.ForeignKey("city_object.id", ondelete="CASCADE"), nullable=False),
        sa.Column("inspection_id", sa.Uuid(), sa.ForeignKey("inspection.id", ondelete="SET NULL")),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("issued_at", sa.Date(), nullable=False),
        sa.Column("deadline", sa.Date(), nullable=False),
        sa.Column("reinspection_date", sa.Date(), nullable=False),
        sa.Column("status", prescription_status_enum, nullable=False, server_default="open"),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("sent_to", sa.Text()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.CheckConstraint("deadline >= issued_at", name="deadline_after_issue"),
        sa.CheckConstraint("reinspection_date >= issued_at", name="reinsp_after_deadline"),
    )
    # инвариант «одна проверка → максимум одно предписание» (частичный UNIQUE)
    op.execute(
        "CREATE UNIQUE INDEX uq_prescription_inspection "
        "ON prescription(inspection_id) WHERE inspection_id IS NOT NULL;"
    )

    # ── (11) Фото ─────────────────────────────────────────────────
    op.create_table(
        "photo",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("object_id", sa.Uuid(), sa.ForeignKey("city_object.id", ondelete="CASCADE"), nullable=False),
        sa.Column("inspection_id", sa.Uuid(), sa.ForeignKey("inspection.id", ondelete="SET NULL")),
        sa.Column("kind", photo_kind_enum, nullable=False, server_default="general"),
        sa.Column("caption", sa.Text()),
        sa.Column("url", sa.Text()),
        sa.Column("color", sa.Text()),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("author", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # ── (12) История объекта (append-only) ────────────────────────
    op.create_table(
        "history_event",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("object_id", sa.Uuid(), sa.ForeignKey("city_object.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", history_type_enum, nullable=False),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # ── (13) Версии карточки объекта ──────────────────────────────
    op.create_table(
        "object_version",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("object_id", sa.Uuid(), sa.ForeignKey("city_object.id", ondelete="CASCADE"), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("author", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("changes", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.CheckConstraint("jsonb_typeof(changes) = 'array'", name="changes_is_array"),
    )

    # ── (14) Уведомления ──────────────────────────────────────────
    op.create_table(
        "notification",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("object_id", sa.Uuid(), sa.ForeignKey("city_object.id", ondelete="SET NULL")),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("read", sa.Boolean(), nullable=False, server_default="false"),
    )

    # ── (15) Refresh-токены ───────────────────────────────────────
    op.create_table(
        "refresh_token",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # ── (16) Идемпотентность POST (Стандарты API §2.2) ────────────
    op.create_table(
        "idempotency_key",
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("fingerprint", sa.Text(), nullable=False),
        sa.Column("response_status", sa.Integer()),
        sa.Column("response_body", postgresql.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # ── (17) Индексы (ER-модель §8) ───────────────────────────────
    op.execute("CREATE INDEX idx_object_status ON city_object(status) WHERE status <> 'archived';")
    op.execute("CREATE INDEX idx_object_md_updated ON city_object(microdistrict_id, updated_at DESC);")
    op.create_index("idx_object_district", "city_object", ["district_id"])
    op.create_index("idx_object_owner", "city_object", ["owner_id"])
    op.create_index("idx_object_type", "city_object", ["type"])
    op.execute("CREATE INDEX idx_object_name_trgm ON city_object USING gin (name gin_trgm_ops);")
    op.execute("CREATE INDEX idx_object_address_trgm ON city_object USING gin (address gin_trgm_ops);")

    op.create_index("idx_inspection_object", "inspection", ["object_id"])
    op.create_index("idx_checklist_inspection", "checklist_item", ["inspection_id"])
    op.create_index("idx_prescription_object", "prescription", ["object_id"])
    op.create_index("idx_photo_object", "photo", ["object_id"])
    op.create_index("idx_version_object", "object_version", ["object_id"])
    op.execute("CREATE INDEX idx_history_object_date ON history_event(object_id, date DESC);")
    op.execute("CREATE INDEX idx_prescription_due ON prescription(deadline) WHERE status = 'open';")
    op.create_index("idx_refresh_user", "refresh_token", ["user_id"])
    op.create_index("idx_refresh_hash", "refresh_token", ["token_hash"])
    op.execute("CREATE INDEX idx_notif_user_unread ON notification(user_id) WHERE read = false;")
    op.create_index("idx_umd_md", "user_microdistrict", ["microdistrict_id"])

    # ── (18) Триггеры (ER-модель §9) ──────────────────────────────
    # (1) append-only история: запрет UPDATE/DELETE
    op.execute(
        """
        CREATE OR REPLACE FUNCTION trg_history_immutable() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'history_event is append-only: % forbidden', TG_OP;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        "CREATE TRIGGER history_no_update BEFORE UPDATE OR DELETE ON history_event "
        "FOR EACH ROW EXECUTE FUNCTION trg_history_immutable();"
    )

    # (2) авто-обновление city_object.updated_at
    op.execute(
        """
        CREATE OR REPLACE FUNCTION trg_touch_updated_at() RETURNS trigger AS $$
        BEGIN
            NEW.updated_at := now();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        "CREATE TRIGGER object_touch BEFORE UPDATE ON city_object "
        "FOR EACH ROW EXECUTE FUNCTION trg_touch_updated_at();"
    )

    # (3) синхронизация денормализованного district_id с районом микрорайона
    op.execute(
        """
        CREATE OR REPLACE FUNCTION trg_object_district_sync() RETURNS trigger AS $$
        BEGIN
            IF NEW.microdistrict_id IS NOT NULL THEN
                SELECT district_id INTO NEW.district_id
                FROM microdistrict WHERE id = NEW.microdistrict_id;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        "CREATE TRIGGER object_district_sync BEFORE INSERT OR UPDATE OF microdistrict_id "
        "ON city_object FOR EACH ROW EXECUTE FUNCTION trg_object_district_sync();"
    )

    # (4) мягкое удаление: физический DELETE объекта запрещён
    op.execute(
        """
        CREATE OR REPLACE FUNCTION trg_object_no_delete() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'city_object is not deletable: set status=''archived'' instead';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        "CREATE TRIGGER object_soft_delete BEFORE DELETE ON city_object "
        "FOR EACH ROW EXECUTE FUNCTION trg_object_no_delete();"
    )


def downgrade() -> None:
    # Триггеры и функции
    op.execute("DROP TRIGGER IF EXISTS object_soft_delete ON city_object;")
    op.execute("DROP TRIGGER IF EXISTS object_district_sync ON city_object;")
    op.execute("DROP TRIGGER IF EXISTS object_touch ON city_object;")
    op.execute("DROP TRIGGER IF EXISTS history_no_update ON history_event;")
    op.execute("DROP FUNCTION IF EXISTS trg_object_no_delete();")
    op.execute("DROP FUNCTION IF EXISTS trg_object_district_sync();")
    op.execute("DROP FUNCTION IF EXISTS trg_touch_updated_at();")
    op.execute("DROP FUNCTION IF EXISTS trg_history_immutable();")

    # Таблицы (обратный порядок зависимостей). CASCADE снимает и индексы/связки.
    op.drop_table("idempotency_key")
    op.drop_table("refresh_token")
    op.drop_table("notification")
    op.drop_table("object_version")
    op.drop_table("history_event")
    op.drop_table("photo")
    op.drop_table("prescription")
    op.drop_table("checklist_item")
    op.drop_table("inspection")
    op.drop_table("city_object")
    op.drop_table("user_microdistrict")
    op.drop_table("app_user")
    op.drop_table("object_type")
    op.drop_table("owner")
    op.drop_table("microdistrict")
    op.drop_table("district")

    # ENUM-типы
    for type_name in (
        "history_type_enum", "photo_kind_enum", "checklist_value_enum", "legal_form_enum",
        "prescription_status_enum", "inspection_result_enum", "object_status_enum",
        "account_status_enum", "role_enum",
    ):
        op.execute(f"DROP TYPE IF EXISTS {type_name};")

    # Расширения оставляем: могут использоваться другими схемами.
