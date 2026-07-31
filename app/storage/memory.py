"""In-memory реализация хранилища (обёртка над app/store.py)."""
from __future__ import annotations

import uuid

from fastapi import HTTPException

from app import config, store
from app.address import DEFAULT_ADDRESS_SCHEMA, DEFAULT_CHECKLIST_ITEMS, build_address
from app.enums import HistoryType, ObjectStatus
from app.models import (
    ChecklistTemplateItem,
    ChecklistTemplateManageItem,
    CityObject,
    CreateObjectRequest,
    CreateOwnerRequest,
    CreateUserRequest,
    Credentials,
    CurrentCity,
    District,
    DistrictCreate,
    GeoConfig,
    GeoConfigPatch,
    HistoryEvent,
    Inspection,
    Microdistrict,
    MicrodistrictCreate,
    ObjectPatch,
    Owner,
    Photo,
    Prescription,
    Street,
    StreetCreate,
    StreetPatch,
    TrendPoint,
    UpdateUserRequest,
    User,
)
from app.user_helpers import login_for, temp_password


def _default_checklist(region_id: str = "uralsk") -> list[ChecklistTemplateItem]:
    return [
        ChecklistTemplateItem(
            id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{region_id}:{item['key']}")),
            key=item["key"],
            titleRu=item["title_ru"],
            titleKz=item["title_kz"],
            category=item["category"],
            sortOrder=item["sort_order"],
            isVisible=True,
        )
        for item in DEFAULT_CHECKLIST_ITEMS
    ]


class MemoryStore:
    def __init__(self) -> None:
        from app.passwords import hash_password
        from app.user_helpers import PLATFORM_SUPERADMIN_PASSWORD, temp_password

        self._region_id: str | None = "uralsk"
        self._password_hashes: dict[str, str] = {}
        for u in store.USERS:
            if u.role.value == "platform_superadmin":
                self._password_hashes[u.id] = hash_password(PLATFORM_SUPERADMIN_PASSWORD)
            else:
                self._password_hashes[u.id] = hash_password(temp_password(u.id))
        self._checklist: dict[str, list[ChecklistTemplateItem]] = {
            "uralsk": _default_checklist("uralsk"),
        }
        self._streets: dict[str, list[Street]] = {"uralsk": []}
        self._geo: dict[str, GeoConfig] = {
            "uralsk": GeoConfig(
                hasDistricts=True,
                hasMicrodistricts=True,
                hasStreets=True,
                addressSchema=DEFAULT_ADDRESS_SCHEMA,
                cityType="city",
                oblast="ЗКО",
            )
        }
        self._city_meta: dict[str, dict[str, str]] = {
            "uralsk": {"name": "Уральск", "code": "uralsk"},
        }
        # Geography is per-region; new cities start empty (no Uralsk copy).
        self._districts: dict[str, list[District]] = {
            "uralsk": list(store.DISTRICTS),
        }
        self._microdistricts: dict[str, list[Microdistrict]] = {
            "uralsk": list(store.MICRODISTRICTS),
        }

    def set_region(self, region_id: str | None) -> None:
        self._region_id = region_id

    def _ensure_same_region(self, row_region_id: str | None) -> None:
        if self._region_id and row_region_id and row_region_id != self._region_id:
            raise HTTPException(
                status_code=403,
                detail={
                    "message": "Нет доступа к данным другого города",
                    "code": "forbidden",
                },
            )

    def seed_checklist_for_region(self, region_id: str) -> None:
        self._checklist[region_id] = _default_checklist(region_id)
        self._streets.setdefault(region_id, [])
        self._districts.setdefault(region_id, [])
        self._microdistricts.setdefault(region_id, [])

    def set_geo_config(self, region_id: str, geo: GeoConfig, *, name: str | None = None) -> None:
        self._geo[region_id] = geo
        if name:
            self._city_meta[region_id] = {"name": name, "code": region_id}
        else:
            self._city_meta.setdefault(region_id, {"name": region_id, "code": region_id})

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass

    def next_id(self, prefix: str) -> str:
        return store.next_id(prefix)

    def list_objects(self) -> list[CityObject]:
        return store.OBJECTS

    def find_object(self, oid: str) -> CityObject | None:
        return store.find_object(oid)

    def create_object(self, body: CreateObjectRequest, actor: User) -> CityObject:
        oid = store.next_id("o")
        street_name = body.street
        if body.streetId:
            st = next(
                (s for s in self._streets.get(self._region_id or "uralsk", []) if s.id == body.streetId),
                None,
            )
            if st:
                street_name = st.name
        md_name = None
        d_name = None
        if body.microdistrictId:
            md = next(
                (m for m in self._microdistricts.get(self._region_id or "uralsk", []) if m.id == body.microdistrictId),
                None,
            )
            md_name = md.name if md else None
        if body.districtId:
            d = next(
                (d for d in self._districts.get(self._region_id or "uralsk", []) if d.id == body.districtId),
                None,
            )
            d_name = d.name if d else None
        geo = self._geo.get(self._region_id or "uralsk")
        schema = geo.addressSchema if geo else DEFAULT_ADDRESS_SCHEMA
        address = body.address or build_address(
            address_schema=schema,
            district_name=d_name,
            microdistrict_name=md_name,
            street_name=street_name,
            house=body.house,
            apartment=body.apartment,
        )
        obj = CityObject(
            id=oid,
            name=body.name,
            type=body.type,
            category=body.category or "—",
            address=address,
            lat=body.lat,
            lng=body.lng,
            districtId=body.districtId,
            microdistrictId=body.microdistrictId,
            street=street_name,
            streetId=body.streetId,
            house=body.house,
            apartment=body.apartment,
            ownerId=body.ownerId or "w4",
            status=ObjectStatus.new,
            responsible=actor.name,
            createdAt=config.today_str(),
            updatedAt=config.today_str(),
        )
        store.OBJECTS.append(obj)
        self.append_history(HistoryEvent(
            id=store.next_id("h"), objectId=oid, type=HistoryType.object_created,
            actor=actor.name, date=config.today_str(), text="Объект создан и добавлен на карту",
        ))
        return obj

    def update_object(self, oid: str, patch: ObjectPatch, note: str | None, actor: str) -> CityObject | None:
        obj = store.find_object(oid)
        if obj is None:
            return None
        data = patch.model_dump(exclude_none=True)
        for k, v in data.items():
            setattr(obj, k, v)
        obj.updatedAt = config.today_str()
        htype = HistoryType.status_changed if "status" in data else HistoryType.card_updated
        self.append_history(HistoryEvent(
            id=store.next_id("h"), objectId=oid, type=htype, actor=actor,
            date=config.today_str(), text=note or "Карточка объекта обновлена",
        ))
        return obj

    def set_object_status(self, oid: str, status: ObjectStatus) -> CityObject | None:
        obj = store.find_object(oid)
        if obj is None:
            return None
        obj.status = status
        obj.updatedAt = config.today_str()
        return obj

    def delete_object(self, oid: str, actor: User) -> CityObject | None:
        """Soft-delete: status → archived."""
        obj = store.find_object(oid)
        if obj is None or obj.status == ObjectStatus.archived:
            return None
        obj.status = ObjectStatus.archived
        obj.updatedAt = config.today_str()
        self.append_history(
            HistoryEvent(
                id=store.next_id("h"),
                objectId=oid,
                type=HistoryType.archived,
                actor=actor.name,
                date=config.today_str(),
                text="Объект удалён администратором района",
            )
        )
        return obj

    def list_inspections(self) -> list[Inspection]:
        return store.INSPECTIONS

    def add_inspection(self, insp: Inspection) -> Inspection:
        if not insp.id:
            insp.id = store.next_id("insp")
        store.INSPECTIONS.append(insp)
        return insp

    def add_photo_if_missing(self, photo: Photo, object_id: str | None = None, inspection_id: str | None = None) -> Photo:
        object_id = object_id or photo.objectId
        if not object_id:
            raise HTTPException(
                status_code=400,
                detail={"message": "objectId обязателен для фото", "code": "bad_request"},
            )
        if photo.id:
            existing = next((p for p in store.PHOTOS if p.id == photo.id), None)
            if existing is not None:
                if not existing.objectId:
                    existing.objectId = object_id
                if photo.url and not existing.url:
                    existing.url = photo.url
                if photo.caption and not existing.caption:
                    existing.caption = photo.caption
                return existing
        if not photo.id:
            photo.id = store.next_id("p")
        photo.objectId = object_id
        store.PHOTOS.append(photo)
        return photo

    def add_prescription(self, pr: Prescription) -> Prescription:
        if not pr.id:
            pr.id = store.next_id("pr")
        store.PRESCRIPTIONS.append(pr)
        return pr

    def list_prescriptions(self) -> list[Prescription]:
        return store.PRESCRIPTIONS

    def find_prescription(self, pid: str) -> Prescription | None:
        return next((p for p in store.PRESCRIPTIONS if p.id == pid), None)

    def patch_prescription(self, pid: str, data: dict) -> Prescription | None:
        pr = self.find_prescription(pid)
        if pr is None:
            return None
        for k, v in data.items():
            setattr(pr, k, v)
        return pr

    def list_users(self) -> list[User]:
        from app.enums import Role
        return [u for u in store.USERS if u.role != Role.platform_superadmin]

    def find_user_by_id(self, uid: str) -> User | None:
        return next((u for u in store.USERS if u.id == uid), None)

    def find_user_by_login(self, login: str) -> User | None:
        return next((u for u in store.USERS if (u.login or "").lower() == login.lower()), None)

    def find_region_admin(self) -> User | None:
        from app.enums import Role
        return next((u for u in store.USERS if u.role == Role.region_admin), None)

    def authenticate_lookup(self, email_or_login: str) -> tuple[User | None, str | None]:
        key = email_or_login.strip().lower()
        login = key.split("@")[0]
        user = next(
            (
                u
                for u in store.USERS
                if (u.login or "").lower() == login
                or (u.email or "").lower() == key
            ),
            None,
        )
        if user is None:
            return None, None
        return user, self._password_hashes.get(user.id)

    def set_password(self, uid_str: str, password: str) -> bool:
        from app.passwords import hash_password

        user = self.find_user_by_id(uid_str)
        if user is None:
            return False
        self._password_hashes[user.id] = hash_password(password)
        return True

    def create_user(self, body: CreateUserRequest) -> tuple[User, Credentials]:
        from app.passwords import hash_password
        from fastapi import HTTPException

        code = store.next_id("u")
        login = login_for(body.name)
        plain = temp_password(code)
        if body.role.value == "owner" and body.ownerId:
            owner = self.find_owner(body.ownerId)
            if owner is None:
                raise HTTPException(
                    400,
                    detail={"message": "Собственник не найден", "code": "owner_not_found"},
                )
            owner.ownerUserId = code
        new = User(
            id=code,
            name=body.name.strip(),
            role=body.role,
            position=body.position.strip(),
            microdistrictIds=body.microdistrictIds if body.role.value == "urbanist" else None,
            ownerObjectIds=(
                [o.id for o in store.OBJECTS if any(
                    ow.id == o.ownerId and ow.ownerUserId == code for ow in store.OWNERS
                )]
                if body.role.value == "owner"
                else None
            ),
            login=login,
            status="active",
            createdAt=config.today_str(),
        )
        # Recompute ownerObjectIds after possible link
        if body.role.value == "owner":
            linked = {ow.id for ow in store.OWNERS if ow.ownerUserId == code}
            new.ownerObjectIds = [o.id for o in store.OBJECTS if o.ownerId in linked]
        store.USERS.append(new)
        self._password_hashes[new.id] = hash_password(plain)
        return new, Credentials(login=login, tempPassword=plain)

    def update_user(self, uid: str, body: UpdateUserRequest) -> tuple[User | None, Credentials | None]:
        from app.passwords import hash_password

        user = self.find_user_by_id(uid)
        if user is None:
            return None, None
        creds = None
        if body.status is not None:
            user.status = body.status
        if body.microdistrictIds is not None:
            user.microdistrictIds = body.microdistrictIds
        if body.resetPassword:
            user.status = "active"
            plain = temp_password(uid)
            self._password_hashes[user.id] = hash_password(plain)
            creds = Credentials(login=user.login or "", tempPassword=plain)
        return user, creds

    def delete_user(self, uid: str) -> User | None:
        from app.enums import Role

        user = self.find_user_by_id(uid)
        if user is None:
            return None
        if user.role in (Role.region_admin, Role.platform_superadmin):
            return None
        store.USERS[:] = [u for u in store.USERS if u.id != uid]
        self._password_hashes.pop(uid, None)
        for owner in store.OWNERS:
            if owner.ownerUserId == uid:
                owner.ownerUserId = None
        return user

    def list_owners(self, owner_user_id: str | None = None) -> list[Owner]:
        items = store.OWNERS
        if owner_user_id:
            items = [o for o in items if o.ownerUserId == owner_user_id]
        return items

    def find_owner(self, wid: str) -> Owner | None:
        return next((o for o in store.OWNERS if o.id == wid), None)

    def create_owner(self, body: CreateOwnerRequest) -> Owner:
        from fastapi import HTTPException
        from app.enums import Role

        if body.ownerUserId:
            user = self.find_user_by_id(body.ownerUserId)
            if user is None or user.role != Role.owner:
                raise HTTPException(
                    422,
                    detail={
                        "message": "ownerUserId must reference an existing User with role=owner",
                        "code": "invalid_owner_user",
                    },
                )
        owner = Owner(id=store.next_id("w"), **body.model_dump())
        store.OWNERS.append(owner)
        return owner

    def update_owner(self, wid: str, body: CreateOwnerRequest) -> Owner | None:
        from fastapi import HTTPException
        from app.enums import Role

        owner = self.find_owner(wid)
        if owner is None:
            return None
        if body.ownerUserId:
            user = self.find_user_by_id(body.ownerUserId)
            if user is None or user.role != Role.owner:
                raise HTTPException(
                    422,
                    detail={
                        "message": "ownerUserId must reference an existing User with role=owner",
                        "code": "invalid_owner_user",
                    },
                )
        for k, v in body.model_dump().items():
            setattr(owner, k, v)
        return owner

    def list_districts(self) -> list[District]:
        region_id = self._region_id or "uralsk"
        return list(self._districts.get(region_id, []))

    def create_district(self, body: DistrictCreate) -> District:
        region_id = self._region_id or "uralsk"
        d = District(id=store.next_id("d"), name=body.name)
        self._districts.setdefault(region_id, []).append(d)
        return d

    def list_microdistricts(self) -> list[Microdistrict]:
        region_id = self._region_id or "uralsk"
        return list(self._microdistricts.get(region_id, []))

    def first_microdistrict(self) -> Microdistrict:
        items = self.list_microdistricts()
        if not items:
            raise LookupError("Нет микрорайонов")
        return items[0]

    def create_microdistrict(self, body: MicrodistrictCreate) -> Microdistrict:
        region_id = self._region_id or "uralsk"
        m = Microdistrict(id=store.next_id("m"), districtId=body.districtId, name=body.name)
        self._microdistricts.setdefault(region_id, []).append(m)
        return m

    def list_object_types(self) -> list[str]:
        return store.OBJECT_TYPES

    def add_object_type(self, type_name: str) -> list[str]:
        if type_name not in store.OBJECT_TYPES:
            store.OBJECT_TYPES.append(type_name)
        return store.OBJECT_TYPES

    def list_photos(self) -> list[Photo]:
        return store.PHOTOS

    def list_history(self) -> list[HistoryEvent]:
        return store.HISTORY

    def append_history(self, event: HistoryEvent) -> HistoryEvent:
        if not event.id:
            event.id = store.next_id("h")
        store.HISTORY.append(event)
        return event

    def list_versions(self):
        return store.VERSIONS

    def inspection_trend(self) -> list[TrendPoint]:
        return store.INSPECTION_TREND

    def list_checklist_template(self, *, visible_only: bool = True) -> list[ChecklistTemplateItem]:
        region_id = self._region_id or "uralsk"
        items = list(self._checklist.get(region_id, []))
        if visible_only:
            items = [i for i in items if i.isVisible]
        return sorted(items, key=lambda i: (i.sortOrder, i.key))

    def manage_checklist_template(
        self, items: list[ChecklistTemplateManageItem]
    ) -> list[ChecklistTemplateItem]:
        region_id = self._region_id or "uralsk"
        current = {i.key: i for i in self._checklist.get(region_id, [])}
        for item in items:
            existing = None
            if item.id:
                existing = next((i for i in current.values() if i.id == item.id), None)
            if existing is None:
                existing = current.get(item.key)
            updated = ChecklistTemplateItem(
                id=existing.id if existing else str(uuid.uuid4()),
                key=item.key,
                titleRu=item.titleRu,
                titleKz=item.titleKz,
                category=item.category,
                sortOrder=item.sortOrder,
                isVisible=item.isVisible,
            )
            current[item.key] = updated
        self._checklist[region_id] = list(current.values())
        return self.list_checklist_template(visible_only=False)

    def list_streets(self) -> list[Street]:
        region_id = self._region_id or "uralsk"
        return list(self._streets.get(region_id, []))

    def create_street(self, body: StreetCreate) -> Street:
        region_id = self._region_id or "uralsk"
        street = Street(
            id=store.next_id("st"),
            name=body.name.strip(),
            districtId=body.districtId,
            microdistrictId=body.microdistrictId,
        )
        self._streets.setdefault(region_id, []).append(street)
        return street

    def update_street(self, sid: str, body: StreetPatch) -> Street | None:
        region_id = self._region_id or "uralsk"
        streets = self._streets.get(region_id, [])
        street = next((s for s in streets if s.id == sid), None)
        if street is None:
            return None
        data = body.model_dump(exclude_unset=True)
        if "name" in data and data["name"] is not None:
            street.name = data["name"].strip()
        if "districtId" in data:
            street.districtId = data["districtId"]
        if "microdistrictId" in data:
            street.microdistrictId = data["microdistrictId"]
        return street

    def delete_street(self, sid: str) -> bool:
        region_id = self._region_id or "uralsk"
        streets = self._streets.get(region_id, [])
        before = len(streets)
        self._streets[region_id] = [s for s in streets if s.id != sid]
        return len(self._streets[region_id]) < before

    def get_geo_config(self, city_id: str) -> GeoConfig:
        if self._region_id and city_id != self._region_id:
            raise HTTPException(
                status_code=403,
                detail={"message": "Нет доступа к данным другого города", "code": "forbidden"},
            )
        geo = self._geo.get(city_id)
        if geo is None:
            raise HTTPException(
                status_code=404,
                detail={"message": "Город не найден", "code": "not_found"},
            )
        return geo

    def update_geo_config(self, city_id: str, body: GeoConfigPatch) -> GeoConfig:
        if self._region_id and city_id != self._region_id:
            raise HTTPException(
                status_code=403,
                detail={"message": "Нет доступа к данным другого города", "code": "forbidden"},
            )
        geo = self._geo.get(city_id)
        if geo is None:
            raise HTTPException(
                status_code=404,
                detail={"message": "Город не найден", "code": "not_found"},
            )
        updated = geo.model_copy(update=body.model_dump(exclude_unset=True))
        self._geo[city_id] = updated
        return updated

    def get_current_city(self) -> CurrentCity:
        city_id = self._region_id
        if not city_id:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "У пользователя нет привязанного города",
                    "code": "no_region",
                },
            )
        geo = self._geo.get(city_id)
        meta = self._city_meta.get(city_id)
        if geo is None or meta is None:
            raise HTTPException(
                status_code=404,
                detail={"message": "Город не найден", "code": "not_found"},
            )
        return CurrentCity(
            id=city_id,
            name=meta["name"],
            code=meta.get("code", city_id),
            hasDistricts=geo.hasDistricts,
            hasMicrodistricts=geo.hasMicrodistricts,
            hasStreets=geo.hasStreets,
            addressSchema=geo.addressSchema,
            cityType=geo.cityType,
            oblast=geo.oblast,
        )
