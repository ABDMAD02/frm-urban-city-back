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
    def __init__(self) -> None:
        from app.passwords import hash_password
        from app.user_helpers import PLATFORM_SUPERADMIN_PASSWORD, temp_password

        self._password_hashes: dict[str, str] = {}
        for u in store.USERS:
            if u.role.value == "platform_superadmin":
                self._password_hashes[u.id] = hash_password(PLATFORM_SUPERADMIN_PASSWORD)
            else:
                self._password_hashes[u.id] = hash_password(temp_password(u.id))

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
            createdAt=config.today_str(), updatedAt=config.today_str(),
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
        if photo not in store.PHOTOS:
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
