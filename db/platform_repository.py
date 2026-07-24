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
    SubscriptionPlan,
    SubscriptionStatus,
)
from app.models import Credentials
from app.platform_models import (
    AdminUser,
    AuditEvent,
    Plan,
    ProvisionRegionRequest,
    Region,
    RegionAdminAccount,
    ReissueAdminRequest,
    Subscription,
    SubscriptionPatch,
)
from app.store import DISTRICTS, MICRODISTRICTS, TYPES
from app.user_helpers import login_for, temp_password
from db.codes import uuid_for_code
from db import models as m
from db.enums import (
    AccountStatus as DbAccountStatus,
    Locale as DbLocale,
    MapProvider as DbMapProvider,
    PlatformAuditAction as DbAuditAction,
    RegionStatus as DbRegionStatus,
    Role as DbRole,
    SubscriptionPlan as DbPlan,
    SubscriptionStatus as DbSubStatus,
)

DEFAULT_REGION = "uralsk"

_STATUS_TRANSITIONS: dict[RegionStatus, set[RegionStatus]] = {
    RegionStatus.trial: {RegionStatus.active, RegionStatus.suspended, RegionStatus.archived},
    RegionStatus.active: {RegionStatus.suspended, RegionStatus.archived},
    RegionStatus.suspended: {RegionStatus.active, RegionStatus.archived},
    RegionStatus.archived: set(),
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


class PlatformStore:
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
        )

    def _usage(self, region_id: str) -> tuple[int, int]:
        users = self._session.scalar(
            select(func.count()).select_from(m.AppUser).where(
                m.AppUser.region_id == region_id,
                m.AppUser.role != DbRole.platform_superadmin,
            )
        ) or 0
        objects = self._session.scalar(
            select(func.count()).select_from(m.CityObject).where(m.CityObject.region_id == region_id)
        ) or 0
        return int(users), int(objects)

    def _subscription(self, row: m.Subscription) -> Subscription:
        used_u, used_o = self._usage(row.region_id)
        return Subscription(
            regionId=row.region_id,
            plan=SubscriptionPlan(row.plan.value),
            status=SubscriptionStatus(row.status.value),
            maxUsers=row.max_users,
            maxObjects=row.max_objects,
            usersUsed=used_u,
            objectsUsed=used_o,
            validFrom=_d(row.valid_from),
            validUntil=_d(row.valid_until),
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
        """Справочники региона: районы / микрорайоны / типы (без объектов)."""
        prefix = "" if region_id == DEFAULT_REGION else f"{region_id}-"
        id_map: dict[str, str] = {}
        for d in DISTRICTS:
            did = f"{prefix}{d.id}"
            id_map[d.id] = did
            self._session.add(m.District(id=did, region_id=region_id, name=d.name))
        self._session.flush()
        for md in MICRODISTRICTS:
            mid = f"{prefix}{md.id}"
            self._session.add(
                m.Microdistrict(
                    id=mid,
                    region_id=region_id,
                    district_id=id_map[md.districtId],
                    name=md.name,
                )
            )
        for t_name, t_cat in TYPES:
            self._session.add(
                m.ObjectType(
                    id=uuid_for_code(f"{region_id}:type:{t_name}"),
                    region_id=region_id,
                    name=t_name,
                    category=t_cat,
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
        row = m.AppUser(
            id=uuid_for_code(code),
            code=code,
            name=name.strip(),
            role=DbRole.region_admin,
            position="Администратор региона",
            login=login,
            email=f"{login}@{region_id}.local",
            status=DbAccountStatus.active,
            region_id=region_id,
            created_at=_now(),
        )
        self._session.add(row)
        self._session.flush()
        creds = Credentials(login=login, tempPassword=temp_password(code))
        return self._region_admin(row), creds

    # ── reads ─────────────────────────────────────────────────────
    def list_regions(self) -> list[Region]:
        rows = self._session.scalars(select(m.Region).order_by(m.Region.created_at)).all()
        return [self._region(r) for r in rows]

    def list_subscriptions(self) -> list[Subscription]:
        rows = self._session.scalars(select(m.Subscription)).all()
        return [self._subscription(r) for r in rows]

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

    def list_plans(self) -> list[Plan]:
        rows = self._session.scalars(select(m.Plan)).all()
        return [
            Plan(
                id=SubscriptionPlan(r.id.value if hasattr(r.id, "value") else r.id),
                label=r.label,
                maxUsers=r.max_users,
                maxObjects=r.max_objects,
                priceHint=r.price_hint,
            )
            for r in rows
        ]

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
    ) -> tuple[Region, Subscription, RegionAdminAccount, Credentials]:
        code = re.sub(r"[^a-z0-9_-]", "", body.code.strip().lower())
        if not code:
            raise ValueError("invalid_code")
        region_id = code
        if self._session.get(m.Region, region_id):
            raise LookupError("region_exists")

        plan_row = self._session.get(m.Plan, DbPlan(body.plan.value))
        if plan_row is None:
            raise LookupError("plan_not_found")

        today = date.today()
        months = 1 if body.plan == SubscriptionPlan.trial else 12
        region = m.Region(
            id=region_id,
            code=code,
            name=body.name.strip(),
            status=DbRegionStatus.trial if body.plan == SubscriptionPlan.trial else DbRegionStatus.active,
            timezone=body.timezone,
            locale=DbLocale(body.locale.value),
            map_provider=DbMapProvider(body.mapProvider.value),
            created_at=_now(),
        )
        self._session.add(region)
        self._session.flush()

        sub = m.Subscription(
            region_id=region_id,
            plan=DbPlan(body.plan.value),
            status=DbSubStatus.active,
            max_users=plan_row.max_users,
            max_objects=plan_row.max_objects,
            valid_from=today,
            valid_until=today + timedelta(days=30 * months),
        )
        self._session.add(sub)
        self._session.flush()

        self._seed_region_refs(region_id)
        account, creds = self._issue_region_admin(region_id=region_id, name=body.adminName)
        self._write_audit(
            region_id=region_id,
            actor=actor,
            action=PlatformAuditAction.region_provisioned,
            detail=f"plan={body.plan.value}; admin={account.login}",
        )
        self._write_audit(
            region_id=region_id,
            actor=actor,
            action=PlatformAuditAction.region_admin_issued,
            detail=account.login,
        )
        self._session.flush()
        return self._region(region), self._subscription(sub), account, creds

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

    def patch_subscription(
        self, region_id: str, body: SubscriptionPatch, *, actor: str
    ) -> Subscription:
        row = self._session.get(m.Subscription, region_id)
        if row is None:
            raise LookupError("subscription_not_found")
        plan_row = self._session.get(m.Plan, DbPlan(body.plan.value))
        if plan_row is None:
            raise LookupError("plan_not_found")
        until = date.fromisoformat(body.validUntil[:10])
        row.plan = DbPlan(body.plan.value)
        row.max_users = plan_row.max_users
        row.max_objects = plan_row.max_objects
        row.valid_until = until
        if until < date.today():
            row.status = DbSubStatus.expired
        else:
            row.status = DbSubStatus.active
        self._write_audit(
            region_id=region_id,
            actor=actor,
            action=PlatformAuditAction.subscription_renewed,
            detail=f"plan={body.plan.value}; until={until.isoformat()}",
        )
        self._session.flush()
        return self._subscription(row)

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

    def check_limits(self, region_id: str, *, users: bool = False, objects: bool = False) -> None:
        sub = self._session.get(m.Subscription, region_id)
        if sub is None:
            raise LookupError("subscription_not_found")
        used_u, used_o = self._usage(region_id)
        if users and used_u >= sub.max_users:
            raise OverflowError("limit_users")
        if objects and used_o >= sub.max_objects:
            raise OverflowError("limit_objects")


def _try_uuid(uid: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(uid)
    except ValueError:
        return None
