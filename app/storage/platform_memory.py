"""In-memory платформенный store для USE_DB=0."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from app.enums import (
    AccountStatus,
    Locale,
    MapProvider,
    PlatformAuditAction,
    RegionStatus,
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
from app.user_helpers import login_for, temp_password
from app.store import DISTRICTS, MICRODISTRICTS, TYPES

_PLANS = [
    Plan(id=SubscriptionPlan.trial, label="Trial", maxUsers=10, maxObjects=50, priceHint="Бесплатно"),
    Plan(id=SubscriptionPlan.standard, label="Standard", maxUsers=50, maxObjects=500, priceHint="По запросу"),
    Plan(id=SubscriptionPlan.pro, label="Pro", maxUsers=200, maxObjects=5000, priceHint="По запросу"),
]


class MemoryPlatformStore:
    def __init__(self) -> None:
        today = date.today().isoformat()
        until = (date.today() + timedelta(days=365)).isoformat()
        self.regions: list[Region] = [
            Region(
                id="uralsk",
                code="uralsk",
                name="Уральск",
                status=RegionStatus.active,
                timezone="Asia/Oral",
                locale=Locale.ru,
                mapProvider=MapProvider.twogis,
                createdAt=today,
            )
        ]
        self.subscriptions: list[Subscription] = [
            Subscription(
                regionId="uralsk",
                plan=SubscriptionPlan.standard,
                status=SubscriptionStatus.active,
                maxUsers=50,
                maxObjects=500,
                usersUsed=3,
                objectsUsed=36,
                validFrom=today,
                validUntil=until,
            )
        ]
        self.admin_users: list[AdminUser] = [
            AdminUser(
                id="sa1",
                name="Platform Superadmin",
                email="super@platform.local",
                role="platform_superadmin",
            )
        ]
        self.region_admins: list[RegionAdminAccount] = [
            RegionAdminAccount(
                id="u3",
                regionId="uralsk",
                name="Асхат Кенжебеков",
                login="a.kenzhebekov",
                role="region_admin",
                status=AccountStatus.active,
                createdAt="2026-05-01",
            )
        ]
        self.plans = list(_PLANS)
        self.audit: list[AuditEvent] = []
        self._ref_seeded: set[str] = {"uralsk"}

    def commit(self) -> None:
        return

    def rollback(self) -> None:
        return

    def list_regions(self) -> list[Region]:
        return list(self.regions)

    def list_subscriptions(self) -> list[Subscription]:
        return list(self.subscriptions)

    def list_admin_users(self) -> list[AdminUser]:
        return list(self.admin_users)

    def list_region_admin_accounts(self) -> list[RegionAdminAccount]:
        return list(self.region_admins)

    def list_plans(self) -> list[Plan]:
        return list(self.plans)

    def list_audit(
        self, *, region_id: str | None = None, limit: int = 50, cursor: str | None = None
    ) -> list[AuditEvent]:
        items = sorted(self.audit, key=lambda e: e.at, reverse=True)
        if region_id:
            items = [e for e in items if e.regionId == region_id]
        if cursor:
            items = [e for e in items if e.at < cursor]
        return items[:limit]

    def find_admin_user_by_id(self, uid: str) -> AdminUser | None:
        return next((u for u in self.admin_users if u.id == uid), None)

    def find_platform_user_by_login_or_email(self, email_or_login: str):
        key = email_or_login.strip().lower()
        login = key.split("@")[0]
        for u in self.admin_users:
            if u.email.lower() == key or u.email.split("@")[0].lower() == login or u.id == login:
                return u
        return None

    def _audit(self, region_id: str, actor: str, action: PlatformAuditAction, detail: str = "") -> None:
        self.audit.append(
            AuditEvent(
                id=f"pa-{len(self.audit)+1}",
                regionId=region_id,
                actor=actor,
                action=action,
                detail=detail,
                at=datetime.now(timezone.utc).isoformat(),
            )
        )

    def provision_region(self, body: ProvisionRegionRequest, *, actor: str):
        code = body.code.strip().lower()
        if any(r.id == code for r in self.regions):
            raise LookupError("region_exists")
        plan = next(p for p in self.plans if p.id == body.plan)
        today = date.today()
        region = Region(
            id=code,
            code=code,
            name=body.name.strip(),
            status=RegionStatus.trial if body.plan == SubscriptionPlan.trial else RegionStatus.active,
            timezone=body.timezone,
            locale=body.locale,
            mapProvider=body.mapProvider,
            createdAt=today.isoformat(),
        )
        months = 1 if body.plan == SubscriptionPlan.trial else 12
        sub = Subscription(
            regionId=code,
            plan=body.plan,
            status=SubscriptionStatus.active,
            maxUsers=plan.maxUsers,
            maxObjects=plan.maxObjects,
            usersUsed=1,
            objectsUsed=0,
            validFrom=today.isoformat(),
            validUntil=(today + timedelta(days=30 * months)).isoformat(),
        )
        login = login_for(body.adminName)
        code_u = f"ra-{code}-1"
        account = RegionAdminAccount(
            id=code_u,
            regionId=code,
            name=body.adminName.strip(),
            login=login,
            role="region_admin",
            status=AccountStatus.active,
            createdAt=today.isoformat(),
        )
        creds = Credentials(login=login, tempPassword=temp_password(code_u))
        self.regions.append(region)
        self.subscriptions.append(sub)
        self.region_admins.append(account)
        self._ref_seeded.add(code)
        self._audit(code, actor, PlatformAuditAction.region_provisioned, f"plan={body.plan.value}")
        self._audit(code, actor, PlatformAuditAction.region_admin_issued, login)
        # touch seed sizes so TYPES/DISTRICTS conceptually exist
        _ = (DISTRICTS, MICRODISTRICTS, TYPES)
        return region, sub, account, creds

    def patch_region_status(self, region_id: str, status: RegionStatus, *, actor: str) -> Region:
        row = next((r for r in self.regions if r.id == region_id), None)
        if row is None:
            raise LookupError("region_not_found")
        transitions = {
            RegionStatus.trial: {RegionStatus.active, RegionStatus.suspended, RegionStatus.archived},
            RegionStatus.active: {RegionStatus.suspended, RegionStatus.archived},
            RegionStatus.suspended: {RegionStatus.active, RegionStatus.archived},
            RegionStatus.archived: set(),
        }
        if status != row.status and status not in transitions.get(row.status, set()):
            raise ValueError("invalid_status_transition")
        updated = row.model_copy(update={"status": status})
        self.regions = [updated if r.id == region_id else r for r in self.regions]
        action = {
            RegionStatus.active: PlatformAuditAction.region_activated,
            RegionStatus.suspended: PlatformAuditAction.region_suspended,
            RegionStatus.archived: PlatformAuditAction.region_archived,
        }.get(status)
        if action:
            self._audit(region_id, actor, action, status.value)
        return updated

    def patch_subscription(self, region_id: str, body: SubscriptionPatch, *, actor: str) -> Subscription:
        row = next((s for s in self.subscriptions if s.regionId == region_id), None)
        if row is None:
            raise LookupError("subscription_not_found")
        plan = next((p for p in self.plans if p.id == body.plan), None)
        if plan is None:
            raise LookupError("plan_not_found")
        updated = row.model_copy(
            update={
                "plan": body.plan,
                "validUntil": body.validUntil[:10],
                "maxUsers": plan.maxUsers,
                "maxObjects": plan.maxObjects,
            }
        )
        self.subscriptions = [updated if s.regionId == region_id else s for s in self.subscriptions]
        self._audit(region_id, actor, PlatformAuditAction.subscription_renewed, body.plan.value)
        return updated

    def reissue_admin(self, region_id: str, body: ReissueAdminRequest, *, actor: str):
        if not any(r.id == region_id for r in self.regions):
            raise LookupError("region_not_found")
        for i, a in enumerate(self.region_admins):
            if a.regionId == region_id and a.status == AccountStatus.active:
                self.region_admins[i] = a.model_copy(update={"status": AccountStatus.blocked})
        login = login_for(body.name)
        code_u = f"ra-{region_id}-{len(self.region_admins)+1}"
        account = RegionAdminAccount(
            id=code_u,
            regionId=region_id,
            name=body.name.strip(),
            login=login,
            role="region_admin",
            status=AccountStatus.active,
            createdAt=date.today().isoformat(),
        )
        creds = Credentials(login=login, tempPassword=temp_password(code_u))
        self.region_admins.append(account)
        self._audit(region_id, actor, PlatformAuditAction.region_admin_reissued, login)
        return account, creds


STORE = MemoryPlatformStore()
