"""ORM-модели Urban City (SQLAlchemy 2.0, style Mapped/mapped_column).

Полное зеркало физической модели из ``02_Спецификация/05_ER_модель.md``:
PK (uuid / текстовый код), FK с политикой ON DELETE, CHECK/UNIQUE/частичные UNIQUE,
нативные ENUM-типы PG, колонка ``version`` для оптимистичной блокировки (Стандарты API §3).
Индексы и триггеры задаются в Alembic-миграции 0001 (не в ORM).
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import Enum as PyEnum
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Double,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base
from .enums import (
    ENUM_TYPE_NAMES,
    AccountStatus,
    ChecklistValue,
    HistoryType,
    InspectionResult,
    LegalForm,
    ObjectStatus,
    PhotoKind,
    PrescriptionStatus,
    Role,
    enum_values,
)


def pg_enum(enum_cls: type[PyEnum]) -> SAEnum:
    """Нативный ENUM-тип PG с именем из ER-модели; значения = value членов enum."""
    return SAEnum(
        enum_cls,
        name=ENUM_TYPE_NAMES[enum_cls],
        values_callable=lambda ec: enum_values(ec),
        native_enum=True,
        create_type=True,  # для Base.metadata.create_all; в миграции create_type=False
    )


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, primary_key=True, server_default=func.gen_random_uuid())


# ── Справочники географии ─────────────────────────────────────────
class District(Base):
    __tablename__ = "district"

    id: Mapped[str] = mapped_column(Text, primary_key=True)  # осмысленный код 'd1'
    name: Mapped[str] = mapped_column(Text, nullable=False)

    microdistricts: Mapped[list[Microdistrict]] = relationship(back_populates="district")


class Microdistrict(Base):
    __tablename__ = "microdistrict"

    id: Mapped[str] = mapped_column(Text, primary_key=True)  # 'm1'
    district_id: Mapped[str] = mapped_column(
        Text, ForeignKey("district.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)

    district: Mapped[District] = relationship(back_populates="microdistricts")


# ── Собственники ──────────────────────────────────────────────────
class Owner(Base):
    __tablename__ = "owner"
    __table_args__ = (
        CheckConstraint(r"bin IS NULL OR bin ~ '^[0-9]{12}$'", name="bin_format"),
        CheckConstraint(
            r"email IS NULL OR email ~* '^[^@\s]+@[^@\s]+\.[^@\s]+$'", name="email_format"
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    code: Mapped[Optional[str]] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    bin: Mapped[Optional[str]] = mapped_column(Text)  # БИН/ИИН, NULL для физлица без ИИН
    phone: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[Optional[str]] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    __mapper_args__ = {"version_id_col": version}


# ── Справочник типов объектов ─────────────────────────────────────
class ObjectType(Base):
    __tablename__ = "object_type"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(Text, unique=True, nullable=False)  # 'Магазин'
    category: Mapped[Optional[str]] = mapped_column(Text)  # 'Торговля'


# ── Пользователи (аккаунты входа) ─────────────────────────────────
class AppUser(Base):
    __tablename__ = "app_user"
    __table_args__ = (
        # владелец обязан быть привязан к карточке собственника
        CheckConstraint("role <> 'owner' OR owner_id IS NOT NULL", name="owner_link"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    code: Mapped[Optional[str]] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[Role] = mapped_column(pg_enum(Role), nullable=False)
    position: Mapped[str] = mapped_column(Text, nullable=False)
    login: Mapped[Optional[str]] = mapped_column(Text, unique=True)
    password_hash: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[AccountStatus] = mapped_column(
        pg_enum(AccountStatus), nullable=False, server_default="active"
    )
    owner_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid, ForeignKey("owner.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    owner: Mapped[Optional[Owner]] = relationship()
    microdistricts: Mapped[list[UserMicrodistrict]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    __mapper_args__ = {"version_id_col": version}


# ── Закрепление сотрудников за микрорайонами (N:M) ────────────────
class UserMicrodistrict(Base):
    __tablename__ = "user_microdistrict"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True
    )
    microdistrict_id: Mapped[str] = mapped_column(
        Text, ForeignKey("microdistrict.id", ondelete="CASCADE"), primary_key=True
    )

    user: Mapped[AppUser] = relationship(back_populates="microdistricts")


# ── Объекты города (корневой агрегат) ─────────────────────────────
class CityObject(Base):
    __tablename__ = "city_object"
    __table_args__ = (
        CheckConstraint("lat BETWEEN -90 AND 90", name="lat_range"),
        CheckConstraint("lng BETWEEN -180 AND 180", name="lng_range"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    code: Mapped[Optional[str]] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(
        Text,
        ForeignKey("object_type.name", onupdate="CASCADE", ondelete="RESTRICT"),
        nullable=False,
    )
    category: Mapped[Optional[str]] = mapped_column(Text)  # денорм. из object_type
    address: Mapped[Optional[str]] = mapped_column(Text)
    lat: Mapped[float] = mapped_column(Double, nullable=False)
    lng: Mapped[float] = mapped_column(Double, nullable=False)
    district_id: Mapped[Optional[str]] = mapped_column(
        Text, ForeignKey("district.id", ondelete="RESTRICT")
    )
    microdistrict_id: Mapped[Optional[str]] = mapped_column(
        Text, ForeignKey("microdistrict.id", ondelete="RESTRICT")
    )
    street: Mapped[Optional[str]] = mapped_column(Text)
    owner_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid, ForeignKey("owner.id", ondelete="RESTRICT")
    )
    status: Mapped[ObjectStatus] = mapped_column(
        pg_enum(ObjectStatus), nullable=False, server_default="new"
    )
    responsible: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    __mapper_args__ = {"version_id_col": version}


# ── Проверки ──────────────────────────────────────────────────────
class Inspection(Base):
    __tablename__ = "inspection"

    id: Mapped[uuid.UUID] = _uuid_pk()
    code: Mapped[Optional[str]] = mapped_column(Text, unique=True)
    object_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("city_object.id", ondelete="CASCADE"), nullable=False
    )
    inspector_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid, ForeignKey("app_user.id", ondelete="SET NULL")
    )
    inspector: Mapped[str] = mapped_column(Text, nullable=False)  # имя-снимок
    date: Mapped[date] = mapped_column(Date, nullable=False)
    result: Mapped[InspectionResult] = mapped_column(pg_enum(InspectionResult), nullable=False)
    comment: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    checklist: Mapped[list[ChecklistItem]] = relationship(
        back_populates="inspection", cascade="all, delete-orphan"
    )


# ── Пункты чек-листа проверки (под-агрегат) ───────────────────────
class ChecklistItem(Base):
    __tablename__ = "checklist_item"
    __table_args__ = (
        UniqueConstraint("inspection_id", "key", name="uq_checklist_key"),  # один критерий/проверку
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    inspection_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("inspection.id", ondelete="CASCADE"), nullable=False
    )
    key: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[ChecklistValue] = mapped_column(pg_enum(ChecklistValue), nullable=False)
    comment: Mapped[Optional[str]] = mapped_column(Text)

    inspection: Mapped[Inspection] = relationship(back_populates="checklist")


# ── Предписания ───────────────────────────────────────────────────
class Prescription(Base):
    __tablename__ = "prescription"
    __table_args__ = (
        CheckConstraint("deadline >= issued_at", name="deadline_after_issue"),
        CheckConstraint("reinspection_date >= issued_at", name="reinsp_after_deadline"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    code: Mapped[Optional[str]] = mapped_column(Text, unique=True)
    object_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("city_object.id", ondelete="CASCADE"), nullable=False
    )
    inspection_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid, ForeignKey("inspection.id", ondelete="SET NULL")
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    issued_at: Mapped[date] = mapped_column(Date, nullable=False)
    deadline: Mapped[date] = mapped_column(Date, nullable=False)
    reinspection_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[PrescriptionStatus] = mapped_column(
        pg_enum(PrescriptionStatus), nullable=False, server_default="open"
    )
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    sent_to: Mapped[Optional[str]] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    __mapper_args__ = {"version_id_col": version}


# ── Фото ──────────────────────────────────────────────────────────
class Photo(Base):
    __tablename__ = "photo"

    id: Mapped[uuid.UUID] = _uuid_pk()
    code: Mapped[Optional[str]] = mapped_column(Text, unique=True)
    object_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("city_object.id", ondelete="CASCADE"), nullable=False
    )
    inspection_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid, ForeignKey("inspection.id", ondelete="SET NULL")
    )
    kind: Mapped[PhotoKind] = mapped_column(
        pg_enum(PhotoKind), nullable=False, server_default="general"
    )
    caption: Mapped[Optional[str]] = mapped_column(Text)
    url: Mapped[Optional[str]] = mapped_column(Text)
    color: Mapped[Optional[str]] = mapped_column(Text)  # плейсхолдер прототипа
    date: Mapped[date] = mapped_column(Date, nullable=False)
    author: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


# ── История объекта (append-only) ─────────────────────────────────
class HistoryEvent(Base):
    __tablename__ = "history_event"

    id: Mapped[uuid.UUID] = _uuid_pk()
    code: Mapped[Optional[str]] = mapped_column(Text, unique=True)
    object_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("city_object.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[HistoryType] = mapped_column(pg_enum(HistoryType), nullable=False)
    actor: Mapped[str] = mapped_column(Text, nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


# ── Версии карточки объекта ───────────────────────────────────────
class ObjectVersion(Base):
    __tablename__ = "object_version"
    __table_args__ = (
        CheckConstraint("jsonb_typeof(changes) = 'array'", name="changes_is_array"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    code: Mapped[Optional[str]] = mapped_column(Text, unique=True)
    object_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("city_object.id", ondelete="CASCADE"), nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    author: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    changes: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")


# ── Уведомления ───────────────────────────────────────────────────
class Notification(Base):
    __tablename__ = "notification"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    object_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid, ForeignKey("city_object.id", ondelete="SET NULL")
    )
    type: Mapped[str] = mapped_column(Text, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    read: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")


# ── Refresh-токены (ротация и отзыв) ──────────────────────────────
class RefreshToken(Base):
    __tablename__ = "refresh_token"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(Text, nullable=False)  # SHA-256, не сам токен
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


# ── Идемпотентность POST (Стандарты API §2.2) ─────────────────────
class IdempotencyKey(Base):
    __tablename__ = "idempotency_key"

    key: Mapped[str] = mapped_column(Text, primary_key=True)  # UUID от клиента
    fingerprint: Mapped[str] = mapped_column(Text, nullable=False)  # hash(метод+путь+тело)
    response_status: Mapped[Optional[int]] = mapped_column(Integer)
    response_body: Mapped[Optional[dict]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
