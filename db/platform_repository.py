"""Платформенный control-plane: регионы, подписки, аудит, провижининг."""
from __future__ import annotations

import re
import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.enums import (
    AccountStatus,
    Locale,
    MapProvider,
    PlatformAuditAction,
    RegionStatus,
    Role,
)
from app.models import Credentials
from app.platform_models import (
    AdminUser,
    AuditEvent,
    GeoProvisionConfig,
    ProvisionRegionRequest,
    Region,
    RegionAdminAccount,
    ReissueAdminRequest,
)
from app.user_helpers import login_for, random_temp_password, temp_password
from app.passwords import hash_password
from db.codes import uuid_for_code
from db import models as m
from db.platform_geo import PlatformGeoMixin
from db.enums import (
    AccountStatus as DbAccountStatus,
    Locale as DbLocale,
    MapProvider as DbMapProvider,
    PlatformAuditAction as DbAuditAction,
    RegionStatus as DbRegionStatus,
    Role as DbRole,
)

DEFAULT_REGION = "uralsk"

_STATUS_TRANSITIONS: dict[RegionStatus, set[RegionStatus]] = {
    RegionStatus.provisioning: set(),  # только POST …/activate
    RegionStatus.trial: {RegionStatus.active, RegionStatus.suspended, RegionStatus.archived},
    RegionStatus.active: {RegionStatus.suspended, RegionStatus.archived},
    RegionStatus.suspended: {RegionStatus.active, RegionStatus.archived},
    # Unarchive: client sends status=active directly.
    RegionStatus.archived: {RegionStatus.active},
}

_STATUS_AUDIT = {
    RegionStatus.active: PlatformAuditAction.region_activated,
    RegionStatus.suspended: PlatformAuditAction.region_suspended,
    RegionStatus.archived: PlatformAuditAction.region_archived,
}


def _d(v: date | datetime | None) -> str:
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.date().isoformat()
    return v.isoformat()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _map_provider(v: MapProvider | DbMapProvider) -> MapProvider:
    raw = v.value if hasattr(v, "value") else str(v)
    return MapProvider(raw)


class PlatformStore(PlatformGeoMixin):
    def __init__(self, session: Session) -> None:
        self._session = session

    def commit(self) -> None:
        self._session.commit()

    def rollback(self) -> None:
        self._session.rollback()

    # ── mappers ───────────────────────────────────────────────────
    def _region(self, row: m.Region) -> Region:
        return Region(
            id=row.id,
            code=row.code,
            name=row.name,
            status=RegionStatus(row.status.value),
            timezone=row.timezone,
            locale=Locale(row.locale.value),
            mapProvider=_map_provider(row.map_provider),
            createdAt=_d(row.created_at),
            cityType=getattr(row, "city_type", None),
            oblast=getattr(row, "oblast", None),
            hasDistricts=bool(getattr(row, "has_districts", True)),
            hasMicrodistricts=bool(getattr(row, "has_microdistricts", True)),
            hasStreets=bool(getattr(row, "has_streets", True)),
            addressSchema=getattr(row, "address_schema", None) or "microdistrict,street,house",
            centerLat=getattr(row, "center_lat", None),
            centerLng=getattr(row, "center_lng", None),
            mapZoom=getattr(row, "map_zoom", None),
        )


    def _admin_user(self, row: m.AppUser) -> AdminUser:
        return AdminUser(
            id=row.code or str(row.id),
            name=row.name,
            email=row.email or (f"{row.login}@platform.local" if row.login else ""),
            role="platform_superadmin",
        )

    def _region_admin(self, row: m.AppUser) -> RegionAdminAccount:
        return RegionAdminAccount(
            id=row.code or str(row.id),
            regionId=row.region_id or "",
            name=row.name,
            login=row.login or "",
            role="region_admin",
            status=AccountStatus(row.status.value),
            createdAt=_d(row.created_at),
        )

    def _audit(self, row: m.PlatformAudit) -> AuditEvent:
        return AuditEvent(
            id=row.id,
            regionId=row.region_id,
            actor=row.actor,
            action=PlatformAuditAction(row.action.value),
            detail=row.detail or "",
            at=row.at.isoformat() if isinstance(row.at, datetime) else str(row.at),
        )

    def _write_audit(
        self,
        *,
        region_id: str,
        actor: str,
        action: PlatformAuditAction,
        detail: str = "",
    ) -> None:
        aid = f"pa-{uuid.uuid4().hex[:12]}"
        self._session.add(
            m.PlatformAudit(
                id=aid,
                region_id=region_id,
                actor=actor,
                action=DbAuditAction(action.value),
                detail=detail,
                at=_now(),
            )
        )

    def _seed_region_refs(self, region_id: str) -> None:
        """Новый регион начинает с пустым списком типов объектов.

        Типы подтягиваются из глобального каталога /object-type-catalog,
        где admin выбирает нужные и добавляет через /object-types/manage.
        Копировать чужой набор (Уральск) нельзя — у каждого города свой контекст.
        """
        self._session.flush()

    def _seed_checklist_template(self, region_id: str) -> None:
        from app.address import DEFAULT_CHECKLIST_ITEMS

        for item in DEFAULT_CHECKLIST_ITEMS:
            self._session.add(
                m.ChecklistTemplate(
                    id=uuid.uuid4(),
                    region_id=region_id,
                    key=item["key"],
                    title_ru=item["title_ru"],
                    title_kz=item["title_kz"],
                    category=item["category"],
                    sort_order=item["sort_order"],
                    is_visible=True,
                )
            )
        self._session.flush()
    def _issue_region_admin(
        self, *, region_id: str, name: str, reissue: bool = False
    ) -> tuple[RegionAdminAccount, Credentials]:
        if reissue:
            for old in self._session.scalars(
                select(m.AppUser).where(
                    m.AppUser.region_id == region_id,
                    m.AppUser.role == DbRole.region_admin,
                )
            ).all():
                old.status = DbAccountStatus.blocked
                if old.login and not old.login.endswith(".blocked"):
                    old.login = f"{old.login}.blocked.{old.code or 'x'}"[:120]

        login = login_for(name)
        # uniqueness
        base = login
        n = 1
        while self._session.scalar(select(m.AppUser).where(m.AppUser.login == login)):
            n += 1
            login = f"{base}{n}"

        code = f"ra-{region_id}-{uuid.uuid4().hex[:6]}"
        plain = random_temp_password()
        row = m.AppUser(
            id=uuid_for_code(code),
            code=code,
            name=name.strip(),
            role=DbRole.region_admin,
            position="Администратор региона",
            login=login,
            email=f"{login}@{region_id}.local",
            password_hash=hash_password(plain),
            password_change_required=True,
            status=DbAccountStatus.active,
            region_id=region_id,
            created_at=_now(),
        )
        self._session.add(row)
        self._session.flush()
        creds = Credentials(login=login, tempPassword=plain)
        return self._region_admin(row), creds

    # ── reads ─────────────────────────────────────────────────────
    def list_regions(self) -> list[Region]:
        rows = self._session.scalars(select(m.Region).order_by(m.Region.created_at)).all()
        return [self._region(r) for r in rows]

    def list_admin_users(self) -> list[AdminUser]:
        rows = self._session.scalars(
            select(m.AppUser).where(m.AppUser.role == DbRole.platform_superadmin)
        ).all()
        return [self._admin_user(r) for r in rows]

    def list_region_admin_accounts(self) -> list[RegionAdminAccount]:
        rows = self._session.scalars(
            select(m.AppUser).where(m.AppUser.role == DbRole.region_admin)
        ).all()
        return [self._region_admin(r) for r in rows]

    def list_audit(
        self,
        *,
        region_id: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> list[AuditEvent]:
        q = select(m.PlatformAudit).order_by(m.PlatformAudit.at.desc(), m.PlatformAudit.id.desc())
        if region_id:
            q = q.where(m.PlatformAudit.region_id == region_id)
        if cursor:
            # cursor = ISO timestamp; return rows strictly older
            try:
                ts = datetime.fromisoformat(cursor.replace("Z", "+00:00"))
                q = q.where(m.PlatformAudit.at < ts)
            except ValueError:
                pass
        q = q.limit(max(1, min(limit, 200)))
        return [self._audit(r) for r in self._session.scalars(q).all()]

    def find_admin_user_by_id(self, uid: str) -> AdminUser | None:
        uid_uuid = _try_uuid(uid)
        q = select(m.AppUser).where(m.AppUser.role == DbRole.platform_superadmin)
        if uid_uuid is not None:
            row = self._session.scalar(q.where((m.AppUser.id == uid_uuid) | (m.AppUser.code == uid)))
        else:
            row = self._session.scalar(q.where(m.AppUser.code == uid))
        return self._admin_user(row) if row else None

    def authenticate_lookup(self, email_or_login: str) -> tuple[AdminUser | None, str | None]:
        row = self.find_platform_user_by_login_or_email(email_or_login)
        if row is None:
            return None, None
        return self._admin_user(row), row.password_hash

    def find_platform_user_by_login_or_email(self, email_or_login: str) -> m.AppUser | None:
        key = email_or_login.strip().lower()
        login = key.split("@")[0]
        return self._session.scalar(
            select(m.AppUser).where(
                m.AppUser.role == DbRole.platform_superadmin,
                (func.lower(m.AppUser.login) == login)
                | (func.lower(m.AppUser.email) == key),
            )
        )

    # ── mutations ─────────────────────────────────────────────────
    def provision_region(
        self, body: ProvisionRegionRequest, *, actor: str
    ) -> tuple[Region, RegionAdminAccount, Credentials]:
        code = re.sub(r"[^a-z0-9_-]", "", body.code.strip().lower())
        if not code:
            raise ValueError("invalid_code")
        # id — непрозрачный стабильный ключ (FK ссылаются на него); code — изменяемый слаг.
        if self._session.scalar(select(m.Region).where(m.Region.code == code)):
            raise LookupError("region_exists")
        region_id = f"reg-{uuid.uuid4().hex[:12]}"

        geo = body.geo
        if geo and geo.source == "catalog":
            if not geo.cityCatalogId:
                raise ValueError("catalog_id_required")
            catalog_id = geo.cityCatalogId
            initial_status = DbRegionStatus.active
        else:
            catalog_id = None
            initial_status = DbRegionStatus.provisioning

        if geo and geo.config:
            cfg = geo.config
        else:
            cfg = GeoProvisionConfig(
                hasDistricts=body.hasDistricts,
                hasMicrodistricts=body.hasMicrodistricts,
                hasStreets=body.hasStreets,
                addressSchema=body.addressSchema,
                cityType=body.cityType,
                oblast=body.oblast,
            )

        region = m.Region(
            id=region_id,
            code=code,
            name=body.name.strip(),
            status=initial_status,
            timezone=body.timezone,
            locale=DbLocale(body.locale.value),
            map_provider=DbMapProvider(body.mapProvider.value),
            created_at=_now(),
        )
        self._session.add(region)
        self._session.flush()
        self._apply_geo_config(region, cfg)

        self._seed_region_refs(region_id)
        self._seed_checklist_template(region_id)
        if catalog_id:
            self.seed_geo_from_catalog(region_id, catalog_id)

        account, creds = self._issue_region_admin(region_id=region_id, name=body.adminName)
        self._write_audit(
            region_id=region_id,
            actor=actor,
            action=PlatformAuditAction.region_provisioned,
            detail=f"admin={account.login}",
        )
        self._write_audit(
            region_id=region_id,
            actor=actor,
            action=PlatformAuditAction.region_admin_issued,
            detail=account.login,
        )
        self._session.flush()
        return self._region(region), account, creds

    def patch_region_status(self, region_id: str, status: RegionStatus, *, actor: str) -> Region:
        row = self._session.get(m.Region, region_id)
        if row is None:
            raise LookupError("region_not_found")
        current = RegionStatus(row.status.value)
        if status == current:
            return self._region(row)
        allowed = _STATUS_TRANSITIONS.get(current, set())
        if status not in allowed:
            raise ValueError("invalid_status_transition")
        row.status = DbRegionStatus(status.value)
        action = _STATUS_AUDIT.get(status)
        if action:
            self._write_audit(region_id=region_id, actor=actor, action=action, detail=status.value)
        self._session.flush()
        return self._region(row)

    def patch_region(self, region_id: str, *, name: str | None = None, code: str | None = None, actor: str) -> Region:
        row = self._session.get(m.Region, region_id)
        if row is None:
            raise LookupError("region_not_found")
        if code is not None:
            new_code = re.sub(r"[^a-z0-9_-]", "", code.strip().lower())
            if new_code and new_code != row.code:
                if self._session.scalar(select(m.Region).where(m.Region.code == new_code)):
                    raise ValueError("region_exists")
                row.code = new_code
        if name is not None and name.strip():
            row.name = name.strip()
        self._session.flush()
        return self._region(row)

    def reissue_admin(
        self, region_id: str, body: ReissueAdminRequest, *, actor: str
    ) -> tuple[RegionAdminAccount, Credentials]:
        if self._session.get(m.Region, region_id) is None:
            raise LookupError("region_not_found")
        account, creds = self._issue_region_admin(
            region_id=region_id, name=body.name, reissue=True
        )
        self._write_audit(
            region_id=region_id,
            actor=actor,
            action=PlatformAuditAction.region_admin_reissued,
            detail=account.login,
        )
        self._session.flush()
        return account, creds

def _try_uuid(uid: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(uid)
    except ValueError:
        return None
