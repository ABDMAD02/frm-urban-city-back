"""In-memory платформенный store для USE_DB=0."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from app.enums import (
    AccountStatus,
    Locale,
    MapProvider,
    PlatformAuditAction,
    RegionStatus,
)
from app.models import (
    Credentials,
    District,
    DistrictCreate,
    DistrictPatch,
    GeoConfig,
    GeoConfigPatch,
    GeoImportRequest,
    GeoImportResponse,
    GeoImportCounts,
    Microdistrict,
    MicrodistrictCreate,
    MicrodistrictPatch,
    Street,
    StreetCreate,
    StreetPatch,
)
from app.platform_models import (
    AdminUser,
    AuditEvent,
    GeoCatalogCityDetail,
    GeoCatalogCitySummary,
    GeoProvisionConfig,
    ProvisionRegionRequest,
    Region,
    RegionAdminAccount,
    ReissueAdminRequest,
)
from app.user_helpers import (
    PLATFORM_SUPERADMIN_EMAIL,
    PLATFORM_SUPERADMIN_PASSWORD,
    login_for,
    random_temp_password,
    temp_password,
)
from app.passwords import hash_password



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
                cityType="city",
                oblast="ЗКО",
                hasDistricts=True,
                hasMicrodistricts=True,
                hasStreets=True,
                addressSchema="microdistrict,street,house",
            )
        ]
        self.admin_users: list[AdminUser] = [
            AdminUser(
                id="sa1",
                name="Platform Superadmin",
                email=PLATFORM_SUPERADMIN_EMAIL,
                role="platform_superadmin",
            )
        ]
        self._password_hashes: dict[str, str] = {
            "sa1": hash_password(PLATFORM_SUPERADMIN_PASSWORD),
        }
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
        self.audit: list[AuditEvent] = []
        self._ref_seeded: set[str] = {"uralsk"}

    def commit(self) -> None:
        return

    def rollback(self) -> None:
        return

    def list_regions(self) -> list[Region]:
        return list(self.regions)

    def list_admin_users(self) -> list[AdminUser]:
        return list(self.admin_users)

    def list_region_admin_accounts(self) -> list[RegionAdminAccount]:
        return list(self.region_admins)

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

    def authenticate_lookup(self, email_or_login: str) -> tuple[AdminUser | None, str | None]:
        admin = self.find_platform_user_by_login_or_email(email_or_login)
        if admin is None or not isinstance(admin, AdminUser):
            return None, None
        return admin, self._password_hashes.get(admin.id)

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

    def find_region(self, region_id: str) -> Region | None:
        return next((r for r in self.regions if r.id == region_id), None)

    def get_region_status(self, region_id: str) -> RegionStatus | None:
        r = self.find_region(region_id)
        return r.status if r else None

    def _operational(self):
        from app.deps import _memory
        return _memory

    def _region_geo_complete(self, region: Region) -> bool:
        mem = self._operational()
        rid = region.id
        if region.hasDistricts and not mem._districts.get(rid):
            return False
        if region.hasMicrodistricts and not mem._microdistricts.get(rid):
            return False
        if region.hasStreets and not mem._streets.get(rid):
            return False
        return True

    def activate_region(self, region_id: str, *, actor: str) -> Region:
        row = self.find_region(region_id)
        if row is None:
            raise LookupError("region_not_found")
        if row.status != RegionStatus.provisioning:
            raise ValueError("not_provisioning")
        if not self._region_geo_complete(row):
            raise ValueError("geo_incomplete")
        updated = row.model_copy(update={"status": RegionStatus.active})
        self.regions = [updated if r.id == region_id else r for r in self.regions]
        self._audit(region_id, actor, PlatformAuditAction.region_activated, "provisioning→active")
        return updated

    def _seed_catalog_geo(self, region_id: str, catalog_id: str) -> None:
        from app.geo_catalog import catalog_by_id

        city = catalog_by_id(catalog_id)
        if city is None:
            raise LookupError("catalog_not_found")
        mem = self._operational()
        cfg = city.get("config") or {}
        mem.set_geo_config(
            region_id,
            GeoConfig(
                hasDistricts=cfg.get("hasDistricts", True),
                hasMicrodistricts=cfg.get("hasMicrodistricts", True),
                hasStreets=cfg.get("hasStreets", True),
                addressSchema=cfg.get("addressSchema", "microdistrict,street,house"),
                cityType=cfg.get("cityType"),
                oblast=city.get("oblast"),
                centerLat=cfg.get("centerLat"),
                centerLng=cfg.get("centerLng"),
                mapZoom=cfg.get("mapZoom"),
            ),
            name=city.get("name"),
        )
        mem._districts[region_id] = []
        mem._microdistricts[region_id] = []
        mem._streets[region_id] = []
        for i, d in enumerate(city.get("districts") or [], start=1):
            did = f"{region_id}-d{i}"
            mem._districts[region_id].append(District(id=did, name=d["name"]))
            for j, md_name in enumerate(d.get("microdistricts") or [], start=1):
                mem._microdistricts[region_id].append(
                    Microdistrict(id=f"{region_id}-m{i}-{j}", districtId=did, name=md_name)
                )
            for j, st_name in enumerate(d.get("streets") or [], start=1):
                mem._streets[region_id].append(
                    Street(id=f"{region_id}-st{i}-{j}", name=st_name, districtId=did)
                )

    def provision_region(self, body: ProvisionRegionRequest, *, actor: str):
        code = body.code.strip().lower()
        if any(r.id == code for r in self.regions):
            raise LookupError("region_exists")
        today = date.today()
        geo = body.geo
        if geo and geo.source == "catalog":
            if not geo.cityCatalogId:
                raise ValueError("catalog_id_required")
            status = RegionStatus.active
        else:
            status = RegionStatus.provisioning

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

        region = Region(
            id=code,
            code=code,
            name=body.name.strip(),
            status=status,
            timezone=body.timezone,
            locale=body.locale,
            mapProvider=body.mapProvider,
            createdAt=today.isoformat(),
            cityType=cfg.cityType,
            oblast=cfg.oblast,
            hasDistricts=cfg.hasDistricts,
            hasMicrodistricts=cfg.hasMicrodistricts,
            hasStreets=cfg.hasStreets,
            addressSchema=cfg.addressSchema,
            centerLat=cfg.centerLat,
            centerLng=cfg.centerLng,
            mapZoom=cfg.mapZoom,
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
        creds = Credentials(login=login, tempPassword=random_temp_password())
        self.regions.append(region)
        self.region_admins.append(account)
        self._ref_seeded.add(code)
        self._audit(code, actor, PlatformAuditAction.region_provisioned, f"admin={login}")
        self._audit(code, actor, PlatformAuditAction.region_admin_issued, login)
        # Mirror checklist + empty geo into operational memory store (no Uralsk copy)
        from app import store as seed_store
        from app.deps import _memory
        from app.enums import AccountStatus as AccStatus, Role
        from app.models import GeoConfig, User

        _memory.seed_checklist_for_region(code)
        _memory.set_geo_config(
            code,
            GeoConfig(
                hasDistricts=cfg.hasDistricts,
                hasMicrodistricts=cfg.hasMicrodistricts,
                hasStreets=cfg.hasStreets,
                addressSchema=cfg.addressSchema,
                cityType=cfg.cityType,
                oblast=cfg.oblast,
                centerLat=cfg.centerLat,
                centerLng=cfg.centerLng,
                mapZoom=cfg.mapZoom,
            ),
            name=body.name.strip(),
        )
        if geo and geo.source == "catalog" and geo.cityCatalogId:
            self._seed_catalog_geo(code, geo.cityCatalogId)
            region = region.model_copy(update={
                "hasDistricts": cfg.hasDistricts,
                "oblast": _memory._geo[code].oblast,
            })
        admin_user = User(
            id=code_u,
            name=body.adminName.strip(),
            role=Role.region_admin,
            position="Администратор региона",
            login=login,
            email=f"{login}@{code}.local",
            status=AccStatus.active,
            createdAt=today.isoformat(),
            regionId=code,
        )
        seed_store.USERS.append(admin_user)
        _memory._password_hashes[code_u] = hash_password(creds.tempPassword)
        return region, account, creds

    def patch_region_status(self, region_id: str, status: RegionStatus, *, actor: str) -> Region:
        row = next((r for r in self.regions if r.id == region_id), None)
        if row is None:
            raise LookupError("region_not_found")
        transitions = {
            RegionStatus.provisioning: set(),
            RegionStatus.trial: {RegionStatus.active, RegionStatus.suspended, RegionStatus.archived},
            RegionStatus.active: {RegionStatus.suspended, RegionStatus.archived},
            RegionStatus.suspended: {RegionStatus.active, RegionStatus.archived},
            # Unarchive: client sends status=active directly.
            RegionStatus.archived: {RegionStatus.active},
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
        creds = Credentials(login=login, tempPassword=random_temp_password())
        self.region_admins.append(account)
        self._audit(region_id, actor, PlatformAuditAction.region_admin_reissued, login)
        return account, creds

    def _with_region(self, region_id: str):
        mem = self._operational()
        prev = mem._region_id
        mem.set_region(region_id)
        return mem, prev

    def list_region_districts(self, region_id: str) -> list[District]:
        if self.find_region(region_id) is None:
            raise LookupError("region_not_found")
        mem, prev = self._with_region(region_id)
        try:
            return mem.list_districts()
        finally:
            mem.set_region(prev)

    def create_region_district(self, region_id: str, body: DistrictCreate) -> District:
        if self.find_region(region_id) is None:
            raise LookupError("region_not_found")
        mem, prev = self._with_region(region_id)
        try:
            for d in mem.list_districts():
                if d.name.lower() == body.name.strip().lower():
                    from fastapi import HTTPException
                    raise HTTPException(409, detail={"message": "Запись с таким названием уже существует", "code": "duplicate_name"})
            return mem.create_district(body)
        finally:
            mem.set_region(prev)

    def update_region_district(self, region_id: str, did: str, body: DistrictPatch) -> District:
        mem, prev = self._with_region(region_id)
        try:
            districts = mem.list_districts()
            row = next((d for d in districts if d.id == did), None)
            if row is None:
                raise LookupError("not_found")
            if body.name:
                for d in districts:
                    if d.id != did and d.name.lower() == body.name.strip().lower():
                        from fastapi import HTTPException
                        raise HTTPException(409, detail={"message": "Запись с таким названием уже существует", "code": "duplicate_name"})
                idx = mem._districts[region_id].index(next(x for x in mem._districts[region_id] if x.id == did))
                mem._districts[region_id][idx] = row.model_copy(update={"name": body.name.strip()})
                return mem._districts[region_id][idx]
            return row
        finally:
            mem.set_region(prev)

    def delete_region_district(self, region_id: str, did: str) -> None:
        mem, prev = self._with_region(region_id)
        try:
            if any(m.districtId == did for m in mem._microdistricts.get(region_id, [])):
                raise ValueError("in_use")
            mem._districts[region_id] = [d for d in mem._districts.get(region_id, []) if d.id != did]
        finally:
            mem.set_region(prev)

    def list_region_microdistricts(self, region_id: str) -> list[Microdistrict]:
        if self.find_region(region_id) is None:
            raise LookupError("region_not_found")
        mem, prev = self._with_region(region_id)
        try:
            return mem.list_microdistricts()
        finally:
            mem.set_region(prev)

    def create_region_microdistrict(self, region_id: str, body: MicrodistrictCreate) -> Microdistrict:
        if self.find_region(region_id) is None:
            raise LookupError("region_not_found")
        mem, prev = self._with_region(region_id)
        try:
            return mem.create_microdistrict(body)
        finally:
            mem.set_region(prev)

    def update_region_microdistrict(self, region_id: str, mid: str, body: MicrodistrictPatch) -> Microdistrict:
        mem, prev = self._with_region(region_id)
        try:
            row = next((m for m in mem.list_microdistricts() if m.id == mid), None)
            if row is None:
                raise LookupError("not_found")
            data = body.model_dump(exclude_unset=True)
            updated = row.model_copy(update={
                k: v for k, v in {
                    "name": data.get("name"),
                    "districtId": data.get("districtId"),
                }.items() if k in data
            })
            mem._microdistricts[region_id] = [
                updated if x.id == mid else x for x in mem._microdistricts.get(region_id, [])
            ]
            return updated
        finally:
            mem.set_region(prev)

    def delete_region_microdistrict(self, region_id: str, mid: str) -> None:
        mem, prev = self._with_region(region_id)
        try:
            mem._microdistricts[region_id] = [
                m for m in mem._microdistricts.get(region_id, []) if m.id != mid
            ]
        finally:
            mem.set_region(prev)

    def list_region_streets(self, region_id: str) -> list[Street]:
        if self.find_region(region_id) is None:
            raise LookupError("region_not_found")
        mem, prev = self._with_region(region_id)
        try:
            return mem.list_streets()
        finally:
            mem.set_region(prev)

    def create_region_street(self, region_id: str, body: StreetCreate) -> Street:
        if self.find_region(region_id) is None:
            raise LookupError("region_not_found")
        mem, prev = self._with_region(region_id)
        try:
            return mem.create_street(body)
        finally:
            mem.set_region(prev)

    def update_region_street(self, region_id: str, sid: str, body: StreetPatch) -> Street:
        mem, prev = self._with_region(region_id)
        try:
            row = next((s for s in mem.list_streets() if s.id == sid), None)
            if row is None:
                raise LookupError("not_found")
            data = body.model_dump(exclude_unset=True)
            updated = row.model_copy(update={k: v for k, v in data.items() if v is not None or k.endswith("Id")})
            mem._streets[region_id] = [updated if s.id == sid else s for s in mem._streets.get(region_id, [])]
            return updated
        finally:
            mem.set_region(prev)

    def delete_region_street(self, region_id: str, sid: str) -> None:
        mem, prev = self._with_region(region_id)
        try:
            mem._streets[region_id] = [s for s in mem._streets.get(region_id, []) if s.id != sid]
        finally:
            mem.set_region(prev)

    def get_region_geo_config(self, region_id: str) -> GeoConfig:
        if self.find_region(region_id) is None:
            raise LookupError("region_not_found")
        mem = self._operational()
        return mem._geo.get(region_id) or GeoConfig(
            hasDistricts=True, hasMicrodistricts=True, hasStreets=True, addressSchema="microdistrict,street,house"
        )

    def patch_region_geo_config(self, region_id: str, body: GeoConfigPatch) -> GeoConfig:
        row = self.find_region(region_id)
        if row is None:
            raise LookupError("region_not_found")
        mem = self._operational()
        current = self.get_region_geo_config(region_id)
        merged = current.model_copy(update=body.model_dump(exclude_unset=True))
        mem.set_geo_config(region_id, merged, name=row.name)
        updated_region = row.model_copy(update=body.model_dump(exclude_unset=True))
        self.regions = [updated_region if r.id == region_id else r for r in self.regions]
        return merged

    def import_region_geo(self, region_id: str, body: GeoImportRequest) -> GeoImportResponse:
        if self.find_region(region_id) is None:
            raise LookupError("region_not_found")
        added = GeoImportCounts()
        skipped = 0
        # Связи резолвим по имени (как в проде на БД); дедуп — по имени уровня.
        district_by_name = {d.name.strip().lower(): d.id for d in self.list_region_districts(region_id)}
        md_by_name = {m.name.strip().lower(): m.id for m in self.list_region_microdistricts(region_id)}
        street_names = {s.name.strip().lower() for s in self.list_region_streets(region_id)}

        for item in body.districts:
            key = item.name.strip().lower()
            if not key or key in district_by_name:
                skipped += 1
                continue
            row = self.create_region_district(region_id, DistrictCreate(name=item.name.strip()))
            district_by_name[key] = row.id
            added.districts += 1

        for item in body.microdistricts:
            key = item.name.strip().lower()
            if not key or key in md_by_name:
                skipped += 1
                continue
            did = item.districtId
            if not did and item.districtName:
                did = district_by_name.get(item.districtName.strip().lower())
            row = self.create_region_microdistrict(
                region_id, MicrodistrictCreate(name=item.name.strip(), districtId=did)
            )
            md_by_name[key] = row.id
            added.microdistricts += 1

        for item in body.streets:
            key = item.name.strip().lower()
            if not key or key in street_names:
                skipped += 1
                continue
            did = item.districtId
            if not did and item.districtName:
                did = district_by_name.get(item.districtName.strip().lower())
            mid = item.microdistrictId
            if not mid and item.microdistrictName:
                mid = md_by_name.get(item.microdistrictName.strip().lower())
            self.create_region_street(
                region_id, StreetCreate(name=item.name.strip(), districtId=did, microdistrictId=mid)
            )
            street_names.add(key)
            added.streets += 1

        return GeoImportResponse(added=added, skipped=skipped)

    def list_geo_catalog_cities(self) -> list[GeoCatalogCitySummary]:
        from app.geo_catalog import GEO_CATALOG_CITIES, catalog_city_summary
        return [GeoCatalogCitySummary(**catalog_city_summary(c)) for c in GEO_CATALOG_CITIES]

    def get_geo_catalog_city(self, city_id: str) -> GeoCatalogCityDetail:
        from app.geo_catalog import catalog_by_id
        city = catalog_by_id(city_id)
        if city is None:
            raise LookupError("catalog_not_found")
        cfg = city.get("config") or {}
        districts, microdistricts, streets = [], [], []
        for i, d in enumerate(city.get("districts") or [], start=1):
            did = f"preview-d{i}"
            districts.append(District(id=did, name=d["name"]))
            for j, md_name in enumerate(d.get("microdistricts") or [], start=1):
                microdistricts.append(Microdistrict(id=f"preview-m{i}-{j}", districtId=did, name=md_name))
            for j, st_name in enumerate(d.get("streets") or [], start=1):
                streets.append(Street(id=f"preview-st{i}-{j}", name=st_name, districtId=did))
        return GeoCatalogCityDetail(
            id=city["id"],
            name=city["name"],
            oblast=city.get("oblast"),
            config=GeoConfig(
                hasDistricts=cfg.get("hasDistricts", True),
                hasMicrodistricts=cfg.get("hasMicrodistricts", True),
                hasStreets=cfg.get("hasStreets", True),
                addressSchema=cfg.get("addressSchema", "microdistrict,street,house"),
                cityType=cfg.get("cityType"),
                oblast=city.get("oblast"),
                centerLat=cfg.get("centerLat"),
                centerLng=cfg.get("centerLng"),
                mapZoom=cfg.get("mapZoom"),
            ),
            districts=districts,
            microdistricts=microdistricts,
            streets=streets,
        )

    def seed_geo_from_catalog(self, region_id: str, catalog_id: str) -> None:
        self._seed_catalog_geo(region_id, catalog_id)


STORE = MemoryPlatformStore()
