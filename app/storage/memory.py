"""In-memory реализация хранилища (обёртка над app/store.py)."""
from __future__ import annotations

from app import config, store
from app.enums import HistoryType, ObjectStatus
from app.models import (
    CityObject,
    CreateObjectRequest,
    CreateOwnerRequest,
    CreateUserRequest,
    Credentials,
    District,
    DistrictCreate,
    HistoryEvent,
    Inspection,
    Microdistrict,
    MicrodistrictCreate,
    ObjectPatch,
    Owner,
    Photo,
    Prescription,
    TrendPoint,
    UpdateUserRequest,
    User,
)
from app.user_helpers import login_for, temp_password


class MemoryStore:
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
        obj = CityObject(
            id=oid, name=body.name, type=body.type,
            category=body.category or "—", address=body.address or "—",
            lat=body.lat, lng=body.lng,
            districtId=body.districtId or "d1", microdistrictId=body.microdistrictId or "m1",
            street=body.street or "—", ownerId=body.ownerId or "w4",
            status=ObjectStatus.new, responsible=actor.name,
            createdAt=config.DEMO_TODAY, updatedAt=config.DEMO_TODAY,
        )
        store.OBJECTS.append(obj)
        self.append_history(HistoryEvent(
            id=store.next_id("h"), objectId=oid, type=HistoryType.object_created,
            actor=actor.name, date=config.DEMO_TODAY, text="Объект создан и добавлен на карту",
        ))
        return obj

    def update_object(self, oid: str, patch: ObjectPatch, note: str | None, actor: str) -> CityObject | None:
        obj = store.find_object(oid)
        if obj is None:
            return None
        data = patch.model_dump(exclude_none=True)
        for k, v in data.items():
            setattr(obj, k, v)
        obj.updatedAt = config.DEMO_TODAY
        htype = HistoryType.status_changed if "status" in data else HistoryType.card_updated
        self.append_history(HistoryEvent(
            id=store.next_id("h"), objectId=oid, type=htype, actor=actor,
            date=config.DEMO_TODAY, text=note or "Карточка объекта обновлена",
        ))
        return obj

    def set_object_status(self, oid: str, status: ObjectStatus) -> CityObject | None:
        obj = store.find_object(oid)
        if obj is None:
            return None
        obj.status = status
        obj.updatedAt = config.DEMO_TODAY
        return obj

    def list_inspections(self) -> list[Inspection]:
        return store.INSPECTIONS

    def add_inspection(self, insp: Inspection) -> Inspection:
        if not insp.id:
            insp.id = store.next_id("insp")
        store.INSPECTIONS.append(insp)
        return insp

    def add_photo_if_missing(self, photo: Photo, object_id: str | None = None, inspection_id: str | None = None) -> Photo:
        if photo not in store.PHOTOS:
            if not photo.id:
                photo.id = store.next_id("p")
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
        return store.USERS

    def find_user_by_id(self, uid: str) -> User | None:
        return next((u for u in store.USERS if u.id == uid), None)

    def find_user_by_login(self, login: str) -> User | None:
        return next((u for u in store.USERS if (u.login or "").lower() == login.lower()), None)

    def find_region_admin(self) -> User | None:
        return next((u for u in store.USERS if u.role.value == "region_admin"), None)

    def create_user(self, body: CreateUserRequest) -> tuple[User, Credentials]:
        seed = store.next_id("u").replace("u", "")
        login = login_for(body.name)
        new = User(
            id=f"u-{seed}", name=body.name.strip(), role=body.role, position=body.position.strip(),
            microdistrictIds=body.microdistrictIds if body.role.value == "urbanist" else None,
            login=login, status="active", createdAt=config.DEMO_TODAY,
        )
        store.USERS.append(new)
        return new, Credentials(login=login, tempPassword=temp_password(seed))

    def update_user(self, uid: str, body: UpdateUserRequest) -> tuple[User | None, Credentials | None]:
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
            creds = Credentials(login=user.login or "", tempPassword=temp_password(uid))
        return user, creds

    def list_owners(self) -> list[Owner]:
        return store.OWNERS

    def find_owner(self, wid: str) -> Owner | None:
        return next((o for o in store.OWNERS if o.id == wid), None)

    def create_owner(self, body: CreateOwnerRequest) -> Owner:
        owner = Owner(id=store.next_id("w"), **body.model_dump())
        store.OWNERS.append(owner)
        return owner

    def update_owner(self, wid: str, body: CreateOwnerRequest) -> Owner | None:
        owner = self.find_owner(wid)
        if owner is None:
            return None
        for k, v in body.model_dump().items():
            setattr(owner, k, v)
        return owner

    def list_districts(self) -> list[District]:
        return store.DISTRICTS

    def create_district(self, body: DistrictCreate) -> District:
        d = District(id=store.next_id("d"), name=body.name)
        store.DISTRICTS.append(d)
        return d

    def list_microdistricts(self) -> list[Microdistrict]:
        return store.MICRODISTRICTS

    def first_microdistrict(self) -> Microdistrict:
        return store.MICRODISTRICTS[0]

    def create_microdistrict(self, body: MicrodistrictCreate) -> Microdistrict:
        m = Microdistrict(id=store.next_id("m"), districtId=body.districtId, name=body.name)
        store.MICRODISTRICTS.append(m)
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
