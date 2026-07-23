"""PostgreSQL-реализация хранилища (зеркало app/store.py API)."""
from __future__ import annotations

import re
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app import config
from app import models as dto
from app.enums import HistoryType, ObjectStatus, PrescriptionStatus
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
from db.enums import AccountStatus, Role
from db import mappers
from db.codes import uuid_for_code
from db import models as m


def _parse_date(s: str) -> date:
    y, mo, d = s.split("-")
    return date(int(y), int(mo), int(d))


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


from app.user_helpers import login_for, temp_password


class DbStore:
    def __init__(self, session: Session) -> None:
        self._session = session
        mappers.set_owner_code_map(self._owner_code_map())
        self._counters = self._load_counters()

    def commit(self) -> None:
        self._session.commit()
        mappers.set_owner_code_map(self._owner_code_map())

    def rollback(self) -> None:
        self._session.rollback()

    # ── lookups ───────────────────────────────────────────────────
    def _owner_code_map(self) -> dict[uuid.UUID, str]:
        rows = self._session.execute(select(m.Owner.id, m.Owner.code))
        return {r.id: r.code for r in rows if r.code}

    def _object_uuid(self, code: str) -> uuid.UUID | None:
        row = self._session.scalar(select(m.CityObject).where(m.CityObject.code == code))
        if row:
            return row.id
        try:
            return uuid.UUID(code)
        except ValueError:
            return None

    def _object_code(self, uid: uuid.UUID) -> str:
        row = self._session.get(m.CityObject, uid)
        return row.code if row and row.code else str(uid)

    def _resolve_uuid(self, model, code: str) -> uuid.UUID | None:
        row = self._session.scalar(select(model).where(model.code == code))
        if row:
            return row.id
        try:
            return uuid.UUID(code)
        except ValueError:
            return None

    def _load_counters(self) -> dict[str, int]:
        # UUID entities expose public ids via ``code``; district/microdistrict use text PK.
        codes: list[str] = []
        for model in (
            m.CityObject,
            m.Owner,
            m.AppUser,
            m.Inspection,
            m.Prescription,
            m.Photo,
            m.HistoryEvent,
            m.ObjectVersion,
        ):
            codes.extend(
                self._session.scalars(select(model.code).where(model.code.is_not(None))).all()
            )
        codes.extend(self._session.scalars(select(m.District.id)).all())
        codes.extend(self._session.scalars(select(m.Microdistrict.id)).all())
        counters: dict[str, int] = {}
        for code in codes:
            mch = re.match(r"^([a-z]+)(\d+)$", code)
            if mch:
                prefix, num = mch.group(1), int(mch.group(2))
                counters[prefix] = max(counters.get(prefix, 0), num)
        counters.setdefault("h", 100)
        counters.setdefault("u", 100)
        return counters

    def next_id(self, prefix: str) -> str:
        self._counters[prefix] = self._counters.get(prefix, 0) + 1
        return f"{prefix}{self._counters[prefix]}"

    # ── objects ───────────────────────────────────────────────────
    def list_objects(self) -> list[CityObject]:
        rows = self._session.scalars(select(m.CityObject)).all()
        return [mappers.city_object(r) for r in rows]

    def find_object(self, oid: str) -> CityObject | None:
        uid = self._object_uuid(oid)
        if uid is None:
            return None
        row = self._session.get(m.CityObject, uid)
        return mappers.city_object(row) if row else None

    def create_object(self, body: CreateObjectRequest, actor: User) -> CityObject:
        code = self.next_id("o")
        owner_uid = self._resolve_uuid(m.Owner, body.ownerId or "w4")
        row = m.CityObject(
            id=uuid_for_code(code),
            code=code,
            name=body.name,
            type=body.type,
            category=body.category or "—",
            address=body.address or "—",
            lat=body.lat,
            lng=body.lng,
            district_id=body.districtId or "d1",
            microdistrict_id=body.microdistrictId or "m1",
            street=body.street or "—",
            owner_id=owner_uid,
            status=ObjectStatus.new,
            responsible=actor.name,
            created_at=_parse_date(config.DEMO_TODAY),
            updated_at=_parse_date(config.DEMO_TODAY),
        )
        self._session.add(row)
        self._session.flush()
        self.append_history(
            HistoryEvent(
                id="", objectId=code, type=HistoryType.object_created,
                actor=actor.name, date=config.DEMO_TODAY,
                text="Объект создан и добавлен на карту",
            )
        )
        return mappers.city_object(row)

    def update_object(self, oid: str, patch: ObjectPatch, note: str | None, actor: str) -> CityObject | None:
        uid = self._object_uuid(oid)
        if uid is None:
            return None
        row = self._session.get(m.CityObject, uid)
        if row is None:
            return None
        data = patch.model_dump(exclude_none=True)
        for k, v in data.items():
            attr = {"districtId": "district_id", "microdistrictId": "microdistrict_id", "ownerId": "owner_id"}.get(k, k)
            if attr == "owner_id" and v is not None:
                setattr(row, attr, self._resolve_uuid(m.Owner, v))
            elif hasattr(row, attr):
                setattr(row, attr, v)
        row.updated_at = _parse_date(config.DEMO_TODAY)
        htype = HistoryType.status_changed if "status" in data else HistoryType.card_updated
        self.append_history(HistoryEvent(
            id="", objectId=oid, type=htype, actor=actor,
            date=config.DEMO_TODAY, text=note or "Карточка объекта обновлена",
        ))
        self._session.flush()
        return mappers.city_object(row)

    def set_object_status(self, oid: str, status: ObjectStatus) -> CityObject | None:
        uid = self._object_uuid(oid)
        row = self._session.get(m.CityObject, uid) if uid else None
        if row is None:
            return None
        row.status = status
        row.updated_at = _parse_date(config.DEMO_TODAY)
        self._session.flush()
        return mappers.city_object(row)

    # ── inspections / prescriptions ───────────────────────────────
    def list_inspections(self) -> list[Inspection]:
        rows = self._session.scalars(
            select(m.Inspection).options(selectinload(m.Inspection.checklist))
        ).all()
        out = []
        for row in rows:
            obj_code = self._object_code(row.object_id)
            photo_ids = self._session.scalars(
                select(m.Photo.code).where(m.Photo.inspection_id == row.id, m.Photo.code.is_not(None))
            ).all()
            out.append(mappers.inspection(row, object_code=obj_code, photo_ids=list(photo_ids)))
        return out

    def add_inspection(self, insp: Inspection) -> Inspection:
        code = insp.id or self.next_id("insp")
        obj_uid = self._object_uuid(insp.objectId)
        row = m.Inspection(
            id=uuid_for_code(code),
            code=code,
            object_id=obj_uid,
            inspector=insp.inspector,
            date=_parse_date(insp.date),
            result=insp.result,
            comment=insp.comment,
        )
        self._session.add(row)
        self._session.flush()
        for item in insp.checklist:
            self._session.add(m.ChecklistItem(
                inspection_id=row.id, key=item.key, label=item.label,
                value=item.value, comment=item.comment,
            ))
        insp.id = code
        return insp

    def add_photo_if_missing(self, photo: Photo, object_id: str | None = None, inspection_id: str | None = None) -> Photo:
        existing = self._session.scalar(select(m.Photo).where(m.Photo.code == photo.id)) if photo.id else None
        if existing:
            return mappers.photo(existing)
        code = photo.id or self.next_id("p")
        obj_uid = self._object_uuid(object_id or "o1")
        insp_uid = self._resolve_uuid(m.Inspection, inspection_id) if inspection_id else None
        row = m.Photo(
            id=uuid_for_code(code),
            code=code,
            object_id=obj_uid,
            inspection_id=insp_uid,
            kind=photo.kind,
            caption=photo.caption,
            color=photo.color or None,
            url=photo.url,
            date=_parse_date(photo.date),
            author=photo.author,
        )
        self._session.add(row)
        self._session.flush()
        photo.id = code
        return photo

    def add_prescription(self, pr: Prescription) -> Prescription:
        code = pr.id or self.next_id("pr")
        obj_uid = self._object_uuid(pr.objectId)
        insp_uid = self._resolve_uuid(m.Inspection, pr.inspectionId)
        row = m.Prescription(
            id=uuid_for_code(code),
            code=code,
            object_id=obj_uid,
            inspection_id=insp_uid,
            title=pr.title,
            description=pr.description,
            issued_at=_parse_date(pr.issuedAt),
            deadline=_parse_date(pr.deadline),
            reinspection_date=_parse_date(pr.reinspectionDate),
            status=pr.status,
        )
        self._session.add(row)
        self._session.flush()
        pr.id = code
        return pr

    def list_prescriptions(self) -> list[Prescription]:
        rows = self._session.scalars(select(m.Prescription)).all()
        out = []
        for row in rows:
            obj_code = self._object_code(row.object_id)
            insp_code = ""
            if row.inspection_id:
                insp = self._session.get(m.Inspection, row.inspection_id)
                insp_code = insp.code if insp and insp.code else str(row.inspection_id)
            out.append(mappers.prescription(row, object_code=obj_code, inspection_code=insp_code))
        return out

    def find_prescription(self, pid: str) -> Prescription | None:
        uid = self._resolve_uuid(m.Prescription, pid)
        if uid is None:
            return None
        row = self._session.get(m.Prescription, uid)
        if row is None:
            return None
        obj_code = self._object_code(row.object_id)
        insp_code = ""
        if row.inspection_id:
            insp = self._session.get(m.Inspection, row.inspection_id)
            insp_code = insp.code if insp and insp.code else str(row.inspection_id)
        return mappers.prescription(row, object_code=obj_code, inspection_code=insp_code)

    def patch_prescription(self, pid: str, data: dict) -> Prescription | None:
        uid = self._resolve_uuid(m.Prescription, pid)
        row = self._session.get(m.Prescription, uid) if uid else None
        if row is None:
            return None
        for k, v in data.items():
            attr = {
                "objectId": "object_id", "inspectionId": "inspection_id",
                "issuedAt": "issued_at", "deadline": "deadline",
                "reinspectionDate": "reinspection_date",
            }.get(k, k)
            if attr.endswith("_at") or attr.endswith("_date"):
                setattr(row, attr, _parse_date(v) if isinstance(v, str) else v)
            elif attr == "object_id":
                setattr(row, attr, self._object_uuid(v))
            elif attr == "inspection_id":
                setattr(row, attr, self._resolve_uuid(m.Inspection, v))
            elif hasattr(row, attr):
                setattr(row, attr, v)
        self._session.flush()
        return self.find_prescription(pid)

    # ── users / auth ──────────────────────────────────────────────
    def list_users(self) -> list[User]:
        rows = self._session.scalars(
            select(m.AppUser).options(selectinload(m.AppUser.microdistricts))
        ).all()
        return [self._map_user(r) for r in rows]

    def find_user_by_id(self, uid_str: str) -> User | None:
        uid = self._resolve_uuid(m.AppUser, uid_str)
        if uid is None:
            return None
        row = self._session.scalar(
            select(m.AppUser)
            .where(m.AppUser.id == uid)
            .options(selectinload(m.AppUser.microdistricts))
        )
        return self._map_user(row) if row else None

    def find_user_by_login(self, login: str) -> User | None:
        row = self._session.scalar(
            select(m.AppUser)
            .where(func.lower(m.AppUser.login) == login.lower())
            .options(selectinload(m.AppUser.microdistricts))
        )
        return self._map_user(row) if row else None

    def find_region_admin(self) -> User | None:
        row = self._session.scalar(
            select(m.AppUser)
            .where(m.AppUser.role == Role.region_admin)
            .options(selectinload(m.AppUser.microdistricts))
        )
        return self._map_user(row) if row else None

    def _map_user(self, row: m.AppUser) -> User:
        md_ids = [um.microdistrict_id for um in row.microdistricts] if row.microdistricts else None
        owner_objs = None
        if row.role.value == "owner" and row.owner_id:
            owner_code = self._owner_code_map().get(row.owner_id)
            if owner_code:
                objs = self._session.scalars(
                    select(m.CityObject.code).where(
                        m.CityObject.owner_id == row.owner_id, m.CityObject.code.is_not(None)
                    )
                ).all()
                owner_objs = list(objs)
        return mappers.user(row, microdistrict_ids=md_ids, owner_object_ids=owner_objs)

    def create_user(self, body: CreateUserRequest) -> tuple[User, Credentials]:
        code = self.next_id("u")
        login = login_for(body.name)
        row = m.AppUser(
            id=uuid_for_code(code),
            code=code,
            name=body.name.strip(),
            role=body.role,
            position=body.position.strip(),
            login=login,
            status=AccountStatus.active,
            created_at=_parse_date(config.DEMO_TODAY),
        )
        self._session.add(row)
        self._session.flush()
        if body.role.value == "urbanist" and body.microdistrictIds:
            for md_id in body.microdistrictIds:
                self._session.add(m.UserMicrodistrict(user_id=row.id, microdistrict_id=md_id))
            self._session.flush()
            self._session.refresh(row, attribute_names=["microdistricts"])
        creds = Credentials(login=login, tempPassword=temp_password(code))
        return self._map_user(row), creds

    def update_user(self, uid_str: str, body: UpdateUserRequest) -> tuple[User | None, Credentials | None]:
        uid = self._resolve_uuid(m.AppUser, uid_str)
        row = self._session.get(m.AppUser, uid) if uid else None
        if row is None:
            return None, None
        creds = None
        if body.status is not None:
            row.status = body.status
        if body.microdistrictIds is not None:
            for um in list(row.microdistricts):
                self._session.delete(um)
            for md_id in body.microdistrictIds:
                self._session.add(m.UserMicrodistrict(user_id=row.id, microdistrict_id=md_id))
        if body.resetPassword:
            row.status = "active"
            creds = Credentials(login=row.login or "", tempPassword=temp_password(uid_str))
        self._session.flush()
        return self._map_user(row), creds

    # ── reference ─────────────────────────────────────────────────
    def list_owners(self) -> list[Owner]:
        return [mappers.owner(r) for r in self._session.scalars(select(m.Owner)).all()]

    def find_owner(self, wid: str) -> Owner | None:
        uid = self._resolve_uuid(m.Owner, wid)
        row = self._session.get(m.Owner, uid) if uid else None
        return mappers.owner(row) if row else None

    def create_owner(self, body: CreateOwnerRequest) -> Owner:
        code = self.next_id("w")
        row = m.Owner(id=uuid_for_code(code), code=code, **{
            "name": body.name,
            "legal_form": body.legalForm,
            "bin": body.bin,
            "phone": body.phone,
            "email": body.email,
        })
        self._session.add(row)
        self._session.flush()
        mappers.set_owner_code_map(self._owner_code_map())
        return mappers.owner(row)

    def update_owner(self, wid: str, body: CreateOwnerRequest) -> Owner | None:
        uid = self._resolve_uuid(m.Owner, wid)
        row = self._session.get(m.Owner, uid) if uid else None
        if row is None:
            return None
        row.name = body.name
        row.legal_form = body.legalForm
        row.bin = body.bin
        row.phone = body.phone
        row.email = body.email
        self._session.flush()
        return mappers.owner(row)

    def list_districts(self) -> list[District]:
        return [mappers.district(r) for r in self._session.scalars(select(m.District)).all()]

    def create_district(self, body: DistrictCreate) -> District:
        code = self.next_id("d")
        row = m.District(id=code, name=body.name)
        self._session.add(row)
        self._session.flush()
        return mappers.district(row)

    def list_microdistricts(self) -> list[Microdistrict]:
        return [mappers.microdistrict(r) for r in self._session.scalars(select(m.Microdistrict)).all()]

    def first_microdistrict(self) -> Microdistrict:
        row = self._session.scalar(select(m.Microdistrict).limit(1))
        if row is None:
            raise LookupError("Нет микрорайонов в БД (нужен seed)")
        return mappers.microdistrict(row)

    def create_microdistrict(self, body: MicrodistrictCreate) -> Microdistrict:
        code = self.next_id("m")
        row = m.Microdistrict(id=code, district_id=body.districtId, name=body.name)
        self._session.add(row)
        self._session.flush()
        return mappers.microdistrict(row)

    def list_object_types(self) -> list[str]:
        return list(self._session.scalars(select(m.ObjectType.name)).all())

    def add_object_type(self, type_name: str) -> list[str]:
        if not self._session.scalar(select(m.ObjectType).where(m.ObjectType.name == type_name)):
            self._session.add(m.ObjectType(name=type_name))
            self._session.flush()
        return self.list_object_types()

    def list_photos(self) -> list[Photo]:
        return [mappers.photo(r) for r in self._session.scalars(select(m.Photo)).all()]

    def list_history(self) -> list[HistoryEvent]:
        rows = self._session.scalars(select(m.HistoryEvent)).all()
        return [mappers.history_event(r, object_code=self._object_code(r.object_id)) for r in rows]

    def append_history(self, event: HistoryEvent) -> HistoryEvent:
        code = event.id or self.next_id("h")
        obj_uid = self._object_uuid(event.objectId)
        row = m.HistoryEvent(
            id=uuid_for_code(code),
            code=code,
            object_id=obj_uid,
            type=event.type,
            actor=event.actor,
            date=_parse_date(event.date),
            text=event.text,
        )
        self._session.add(row)
        self._session.flush()
        event.id = code
        return event

    def list_versions(self) -> list[dto.ObjectVersion]:
        rows = self._session.scalars(select(m.ObjectVersion)).all()
        return [mappers.object_version(r, object_code=self._object_code(r.object_id)) for r in rows]

    def inspection_trend(self) -> list[TrendPoint]:
        from app import store as seed

        return seed.INSPECTION_TREND
