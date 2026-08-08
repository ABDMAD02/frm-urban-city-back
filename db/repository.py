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


from app.user_helpers import login_for, random_temp_password, temp_password


class DbStore:
    def __init__(self, session: Session, *, region_id: str | None = "uralsk") -> None:
        self._session = session
        self._region_id = region_id
        self._counters = self._load_counters()

    def set_region(self, region_id: str | None) -> None:
        self._region_id = region_id

    def _ensure_same_region(self, row_region_id: str | None) -> None:
        """403 if row belongs to another city (tenant isolation)."""
        from fastapi import HTTPException

        if self._region_id and row_region_id and row_region_id != self._region_id:
            raise HTTPException(
                status_code=403,
                detail={
                    "message": "Нет доступа к данным другого города",
                    "code": "forbidden",
                },
            )

    def commit(self) -> None:
        self._session.commit()

    def rollback(self) -> None:
        self._session.rollback()

    # ── lookups ───────────────────────────────────────────────────


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
        codes.extend(
            self._session.scalars(select(m.Street.code).where(m.Street.code.is_not(None))).all()
        )
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
    def _require_owner_uuid(self, owner_id: str | None, *, region_id: str) -> uuid.UUID:
        """Resolve public owner id (w11) → UUID; 422 if missing / wrong region."""
        from fastapi import HTTPException

        public = owner_id or "w4"
        uid = self._resolve_uuid(m.Owner, public)
        row = self._session.get(m.Owner, uid) if uid else None
        if row is None:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": f"ownerId must reference an existing Owner (got {public!r})",
                    "code": "invalid_owner",
                },
            )
        if row.region_id and row.region_id != region_id:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "ownerId must belong to the same region",
                    "code": "invalid_owner_region",
                },
            )
        return row.id

    def _city_object_dto(self, row: m.CityObject) -> CityObject:
        # Ensure relationship is loaded so mapper returns short code (w11), not UUID.
        if row.owner_id and row.__dict__.get("owner") is None:
            row.owner = self._session.get(m.Owner, row.owner_id)
        if row.street_id and row.__dict__.get("street_row") is None:
            row.street_row = self._session.get(m.Street, row.street_id)
        if row.assigned_urbanist_id and row.__dict__.get("assigned_urbanist") is None:
            row.assigned_urbanist = self._session.get(m.AppUser, row.assigned_urbanist_id)
        return mappers.city_object(row)

    def list_objects(self) -> list[CityObject]:
        q = select(m.CityObject).options(
            selectinload(m.CityObject.owner),
            selectinload(m.CityObject.street_row),
            selectinload(m.CityObject.assigned_urbanist),
        )
        if self._region_id:
            q = q.where(m.CityObject.region_id == self._region_id)
        rows = self._session.scalars(q).all()
        return [mappers.city_object(r) for r in rows]

    def find_object(self, oid: str) -> CityObject | None:
        uid = self._object_uuid(oid)
        if uid is None:
            return None
        row = self._session.get(
            m.CityObject,
            uid,
            options=(
                selectinload(m.CityObject.owner),
                selectinload(m.CityObject.street_row),
                selectinload(m.CityObject.assigned_urbanist),
            ),
        )
        if row is None:
            return None
        self._ensure_same_region(row.region_id)
        return self._city_object_dto(row)

    def create_object(self, body: CreateObjectRequest, actor: User) -> CityObject:
        from app.address import DEFAULT_ADDRESS_SCHEMA, build_address

        region_id = actor.regionId or self._region_id or "uralsk"
        code = self.next_id("o")
        owner_uid = self._require_owner_uuid(body.ownerId, region_id=region_id)
        district_id = body.districtId
        microdistrict_id = body.microdistrictId
        street_uid = self._resolve_uuid(m.Street, body.streetId) if body.streetId else None
        street_name = body.street
        if street_uid:
            st = self._session.get(m.Street, street_uid)
            if st:
                self._ensure_same_region(st.region_id)
                street_name = st.name
        region = self._session.get(m.Region, region_id)
        schema = (region.address_schema if region else None) or DEFAULT_ADDRESS_SCHEMA
        md_name = None
        d_name = None
        if microdistrict_id:
            md = self._session.get(m.Microdistrict, microdistrict_id)
            md_name = md.name if md else None
        if district_id:
            d = self._session.get(m.District, district_id)
            d_name = d.name if d else None
        address = body.address or build_address(
            address_schema=schema,
            district_name=d_name,
            microdistrict_name=md_name,
            street_name=street_name,
            house=body.house,
            apartment=body.apartment,
        )
        row = m.CityObject(
            id=uuid_for_code(code),
            code=code,
            region_id=region_id,
            name=body.name,
            type=body.type,
            category=body.category or "—",
            address=address,
            lat=body.lat,
            lng=body.lng,
            district_id=district_id,
            microdistrict_id=microdistrict_id,
            street=street_name or "—",
            street_id=street_uid,
            house=body.house,
            apartment=body.apartment,
            owner_id=owner_uid,
            status=ObjectStatus.new,
            responsible=actor.name,
            created_at=_parse_date(config.today_str()),
            updated_at=_parse_date(config.today_str()),
        )
        self._session.add(row)
        self._session.flush()
        self.append_history(
            HistoryEvent(
                id="", objectId=code, type=HistoryType.object_created,
                actor=actor.name, date=config.today_str(),
                text="Объект создан и добавлен на карту",
            )
        )
        return self._city_object_dto(row)

    def update_object(self, oid: str, patch: ObjectPatch, note: str | None, actor: str) -> CityObject | None:
        from app.address import DEFAULT_ADDRESS_SCHEMA, build_address

        uid = self._object_uuid(oid)
        if uid is None:
            return None
        row = self._session.get(m.CityObject, uid)
        if row is None:
            return None
        self._ensure_same_region(row.region_id)
        data = patch.model_dump(exclude_none=True)
        geo_keys = {
            "districtId", "microdistrictId", "streetId", "street", "house", "apartment", "address",
        }
        rebuild_address = bool(geo_keys & data.keys()) and "address" not in data
        for k, v in data.items():
            attr = {
                "districtId": "district_id",
                "microdistrictId": "microdistrict_id",
                "ownerId": "owner_id",
                "streetId": "street_id",
            }.get(k, k)
            if attr == "owner_id" and v is not None:
                region_id = row.region_id or self._region_id or "uralsk"
                row.owner_id = self._require_owner_uuid(v, region_id=region_id)
                # Drop cached relationship so DTO reloads the new owner code.
                if "owner" in row.__dict__:
                    del row.__dict__["owner"]
            elif attr == "street_id":
                street_uid = self._resolve_uuid(m.Street, v) if v else None
                if street_uid:
                    st = self._session.get(m.Street, street_uid)
                    if st:
                        self._ensure_same_region(st.region_id)
                        row.street = st.name
                row.street_id = street_uid
                if "street_row" in row.__dict__:
                    del row.__dict__["street_row"]
            elif hasattr(row, attr):
                setattr(row, attr, v)
        if rebuild_address:
            region = self._session.get(m.Region, row.region_id) if row.region_id else None
            schema = (region.address_schema if region else None) or DEFAULT_ADDRESS_SCHEMA
            md_name = None
            d_name = None
            if row.microdistrict_id:
                md = self._session.get(m.Microdistrict, row.microdistrict_id)
                md_name = md.name if md else None
            if row.district_id:
                d = self._session.get(m.District, row.district_id)
                d_name = d.name if d else None
            row.address = build_address(
                address_schema=schema,
                district_name=d_name,
                microdistrict_name=md_name,
                street_name=row.street,
                house=row.house,
                apartment=row.apartment,
            )
        # assignedUrbanistId: явный null = снять override (exclude_none его глотает).
        if "assignedUrbanistId" in patch.model_fields_set:
            aid = patch.assignedUrbanistId
            row.assigned_urbanist_id = self._resolve_uuid(m.AppUser, aid) if aid else None
            if "assigned_urbanist" in row.__dict__:
                del row.__dict__["assigned_urbanist"]
        row.updated_at = _parse_date(config.today_str())
        htype = HistoryType.status_changed if "status" in data else HistoryType.card_updated
        self.append_history(HistoryEvent(
            id="", objectId=oid, type=htype, actor=actor,
            date=config.today_str(), text=note or "Карточка объекта обновлена",
        ))
        self._session.flush()
        return self._city_object_dto(row)

    def set_object_status(self, oid: str, status: ObjectStatus) -> CityObject | None:
        uid = self._object_uuid(oid)
        row = self._session.get(m.CityObject, uid) if uid else None
        if row is None:
            return None
        self._ensure_same_region(row.region_id)
        row.status = status
        row.updated_at = _parse_date(config.today_str())
        self._session.flush()
        return self._city_object_dto(row)

    def delete_object(self, oid: str, actor: User) -> CityObject | None:
        """Soft-delete: status → archived (DB trigger forbids physical DELETE)."""
        uid = self._object_uuid(oid)
        if uid is None:
            return None
        row = self._session.get(m.CityObject, uid)
        if row is None or row.status == ObjectStatus.archived:
            return None
        self._ensure_same_region(row.region_id)
        row.status = ObjectStatus.archived
        row.updated_at = _parse_date(config.today_str())
        self.append_history(
            HistoryEvent(
                id="",
                objectId=oid,
                type=HistoryType.archived,
                actor=actor.name,
                date=config.today_str(),
                text="Объект удалён администратором района",
            )
        )
        self._session.flush()
        return self._city_object_dto(row)

    # ── inspections / prescriptions ───────────────────────────────
    def list_inspections(self) -> list[Inspection]:
        q = select(m.Inspection).options(
            selectinload(m.Inspection.checklist),
            selectinload(m.Inspection.inspector_user),
        )
        if self._region_id:
            q = q.join(m.CityObject, m.Inspection.object_id == m.CityObject.id).where(
                m.CityObject.region_id == self._region_id
            )
        rows = self._session.scalars(q).all()
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
        if obj_uid is not None:
            obj = self._session.get(m.CityObject, obj_uid)
            if obj is not None:
                self._ensure_same_region(obj.region_id)
        row = m.Inspection(
            id=uuid_for_code(code),
            code=code,
            object_id=obj_uid,
            inspector_id=self._resolve_uuid(m.AppUser, insp.inspectorId) if insp.inspectorId else None,
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
        # Link any pre-uploaded photos referenced by photoIds
        for pid in insp.photoIds or []:
            prow = self._session.scalar(select(m.Photo).where(m.Photo.code == pid))
            if prow is not None:
                prow.inspection_id = row.id
                if obj_uid and prow.object_id != obj_uid:
                    prow.object_id = obj_uid
        self._session.flush()
        insp.id = code
        return insp

    def add_photo_if_missing(self, photo: Photo, object_id: str | None = None, inspection_id: str | None = None) -> Photo:
        from fastapi import HTTPException

        object_id = object_id or photo.objectId
        if not object_id:
            raise HTTPException(
                status_code=400,
                detail={"message": "objectId обязателен для фото", "code": "bad_request"},
            )
        existing = (
            self._session.scalar(select(m.Photo).where(m.Photo.code == photo.id)) if photo.id else None
        )
        if existing:
            obj = self._session.get(m.CityObject, existing.object_id) if existing.object_id else None
            if obj is not None:
                self._ensure_same_region(obj.region_id)
            obj_uid = self._object_uuid(object_id)
            if obj_uid and existing.object_id != obj_uid:
                existing.object_id = obj_uid
            if inspection_id:
                insp_uid = self._resolve_uuid(m.Inspection, inspection_id)
                if insp_uid:
                    existing.inspection_id = insp_uid
            if photo.url:
                existing.url = photo.url
            if photo.caption:
                existing.caption = photo.caption
            if photo.kind is not None:
                existing.kind = photo.kind
            if photo.author:
                existing.author = photo.author
            self._session.flush()
            return mappers.photo(existing, object_code=self._object_code(existing.object_id))

        code = (photo.id or "").strip() or self.next_id("p")
        obj_uid = self._object_uuid(object_id)
        if obj_uid is None:
            raise HTTPException(
                status_code=404,
                detail={"message": "Объект не найден", "code": "not_found"},
            )
        obj = self._session.get(m.CityObject, obj_uid)
        if obj is not None:
            self._ensure_same_region(obj.region_id)
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
            date=_parse_date(photo.date) if photo.date else _parse_date(config.today_str()),
            author=photo.author or "",
        )
        self._session.add(row)
        self._session.flush()
        return mappers.photo(row, object_code=object_id)

    def find_photo(self, pid: str) -> Photo | None:
        row = self._session.scalar(select(m.Photo).where(m.Photo.code == pid))
        if row is None:
            return None
        obj = self._session.get(m.CityObject, row.object_id) if row.object_id else None
        if obj is not None:
            self._ensure_same_region(obj.region_id)
        return mappers.photo(row, object_code=self._object_code(row.object_id))

    def list_photos_for_inspection(self, inspection_id: str) -> list[Photo]:
        insp_uid = self._resolve_uuid(m.Inspection, inspection_id)
        if insp_uid is None:
            return []
        rows = self._session.scalars(
            select(m.Photo).where(m.Photo.inspection_id == insp_uid)
        ).all()
        return [mappers.photo(r, object_code=self._object_code(r.object_id)) for r in rows]

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
        q = select(m.Prescription)
        if self._region_id:
            q = q.join(m.CityObject, m.Prescription.object_id == m.CityObject.id).where(
                m.CityObject.region_id == self._region_id
            )
        rows = self._session.scalars(q).all()
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
        if row.object_id:
            obj = self._session.get(m.CityObject, row.object_id)
            if obj is not None:
                self._ensure_same_region(obj.region_id)
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
        if row.object_id:
            obj = self._session.get(m.CityObject, row.object_id)
            if obj is not None:
                self._ensure_same_region(obj.region_id)
        for k, v in data.items():
            attr = {
                "objectId": "object_id", "inspectionId": "inspection_id",
                "issuedAt": "issued_at", "deadline": "deadline",
                "reinspectionDate": "reinspection_date",
            }.get(k, k)
            if attr in ("issued_at", "deadline", "reinspection_date"):
                setattr(row, attr, _parse_date(v) if isinstance(v, str) else v)
            elif attr == "object_id":
                setattr(row, attr, self._object_uuid(v))
            elif attr == "inspection_id":
                setattr(row, attr, self._resolve_uuid(m.Inspection, v))
            elif hasattr(row, attr):
                setattr(row, attr, v)
        self._session.flush()
        return self.find_prescription(pid)

    def mark_prescription_sent(self, pid: str, to: str | None) -> str | None:
        """Зафиксировать выдачу уведомления ответственному лицу (sent_at/sent_to).

        Реальной доставки (email/Telegram) пока нет — уведомление бумажное,
        выдаётся лично. Здесь фиксируется момент и адресат выдачи как аудит-след,
        а не факт электронной отправки.
        """
        from datetime import datetime, timezone

        uid = self._resolve_uuid(m.Prescription, pid)
        row = self._session.get(m.Prescription, uid) if uid else None
        if row is None:
            return None
        now = datetime.now(timezone.utc).replace(microsecond=0)
        row.sent_at = now
        row.sent_to = to
        self._session.flush()
        return now.isoformat().replace("+00:00", "Z")

    # ── users / auth ──────────────────────────────────────────────
    def list_users(self) -> list[User]:
        q = select(m.AppUser).options(selectinload(m.AppUser.microdistricts), selectinload(m.AppUser.streets)).where(
            m.AppUser.role != Role.platform_superadmin
        )
        if self._region_id:
            q = q.where(m.AppUser.region_id == self._region_id)
        rows = self._session.scalars(q).all()
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
        if row is None:
            return None
        if row.role != Role.platform_superadmin:
            self._ensure_same_region(row.region_id)
        return self._map_user(row)

    def find_user_by_login(self, login: str) -> User | None:
        row = self._session.scalar(
            select(m.AppUser)
            .where(func.lower(m.AppUser.login) == login.lower())
            .options(selectinload(m.AppUser.microdistricts))
        )
        return self._map_user(row) if row else None

    def authenticate_lookup(self, email_or_login: str) -> tuple[User | None, str | None]:
        """Найти пользователя по email/login и вернуть (User, password_hash)."""
        key = email_or_login.strip().lower()
        login = key.split("@")[0]
        row = self._session.scalar(
            select(m.AppUser)
            .where(
                (func.lower(m.AppUser.login) == login)
                | (func.lower(m.AppUser.email) == key)
            )
            .options(selectinload(m.AppUser.microdistricts))
        )
        if row is None:
            return None, None
        return self._map_user(row), row.password_hash

    def set_password(self, uid_str: str, password: str) -> bool:
        from app.passwords import hash_password

        uid = self._resolve_uuid(m.AppUser, uid_str)
        row = self._session.get(m.AppUser, uid) if uid else None
        if row is None:
            row = self._session.scalar(select(m.AppUser).where(m.AppUser.code == uid_str))
        if row is None:
            return False
        row.password_hash = hash_password(password)
        self._session.flush()
        return True

    def _map_user(self, row: m.AppUser) -> User:
        md_ids = [um.microdistrict_id for um in row.microdistricts] if row.microdistricts else None
        st_ids = None
        if row.streets:
            st_uids = [us.street_id for us in row.streets]
            st_ids = list(
                self._session.scalars(
                    select(m.Street.code).where(m.Street.id.in_(st_uids), m.Street.code.is_not(None))
                ).all()
            ) or None
        owner_objs = None
        if row.role.value == "owner":
            business_ids = list(
                self._session.scalars(
                    select(m.Owner.id).where(m.Owner.owner_user_id == row.id)
                ).all()
            )
            # Legacy fallback: AppUser.owner_id
            if not business_ids and row.owner_id:
                business_ids = [row.owner_id]
            if business_ids:
                objs = self._session.scalars(
                    select(m.CityObject.code).where(
                        m.CityObject.owner_id.in_(business_ids),
                        m.CityObject.code.is_not(None),
                    )
                ).all()
                owner_objs = list(objs)
        return mappers.user(row, microdistrict_ids=md_ids, street_ids=st_ids, owner_object_ids=owner_objs)

    def _user_public_id(self, uid: uuid.UUID | None) -> str | None:
        if uid is None:
            return None
        row = self._session.get(m.AppUser, uid)
        if row is None:
            return None
        return row.code or str(row.id)

    def _owner_dto(self, row: m.Owner) -> Owner:
        return mappers.owner(row, owner_user_id=self._user_public_id(row.owner_user_id))

    def _resolve_owner_account(
        self, owner_user_id: str | None, *, region_id: str
    ) -> uuid.UUID | None:
        """Validate ownerUserId → AppUser(role=owner) in region. Raises HTTP 422."""
        from fastapi import HTTPException

        if owner_user_id is None or owner_user_id == "":
            return None
        uid = self._resolve_uuid(m.AppUser, owner_user_id)
        user = self._session.get(m.AppUser, uid) if uid else None
        if user is None or user.role.value != "owner":
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "ownerUserId must reference an existing User with role=owner",
                    "code": "invalid_owner_user",
                },
            )
        if user.region_id and user.region_id != region_id:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "ownerUserId must belong to the same region",
                    "code": "owner_user_region_mismatch",
                },
            )
        return user.id

    def create_user(self, body: CreateUserRequest) -> tuple[User, Credentials]:
        from fastapi import HTTPException

        from app.passwords import hash_password

        region_id = self._region_id or "uralsk"
        code = self.next_id("u")
        login = login_for(body.name)
        plain = random_temp_password()

        row = m.AppUser(
            id=uuid_for_code(code),
            code=code,
            name=body.name.strip(),
            role=body.role,
            position=body.position.strip(),
            login=login,
            password_hash=hash_password(plain),
            status=AccountStatus.active,
            region_id=region_id,
            owner_id=None,
            created_at=_parse_date(config.today_str()),
        )
        self._session.add(row)
        self._session.flush()

        # Optional: link existing business(es) card to this new account.
        if body.role.value == "owner" and body.ownerId:
            owner_uid = self._resolve_uuid(m.Owner, body.ownerId)
            owner_row = self._session.get(m.Owner, owner_uid) if owner_uid else None
            if owner_row is None:
                raise HTTPException(
                    status_code=400,
                    detail={"message": "Собственник не найден", "code": "owner_not_found"},
                )
            if owner_row.region_id and owner_row.region_id != region_id:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "message": "Owner and user must be in the same region",
                        "code": "owner_user_region_mismatch",
                    },
                )
            owner_row.owner_user_id = row.id
            # Keep legacy column for older clients (non-unique now).
            row.owner_id = owner_row.id
            self._session.flush()

        if body.role.value == "urbanist" and body.microdistrictIds:
            for md_id in body.microdistrictIds:
                self._session.add(m.UserMicrodistrict(user_id=row.id, microdistrict_id=md_id))
            self._session.flush()
            self._session.refresh(row, attribute_names=["microdistricts"])
        creds = Credentials(login=login, tempPassword=plain)
        return self._map_user(row), creds

    def update_user(self, uid_str: str, body: UpdateUserRequest) -> tuple[User | None, Credentials | None]:
        uid = self._resolve_uuid(m.AppUser, uid_str)
        row = self._session.get(m.AppUser, uid) if uid else None
        if row is None:
            return None, None
        self._ensure_same_region(row.region_id)
        creds = None
        if body.status is not None:
            row.status = body.status
        if body.microdistrictIds is not None:
            for um in list(row.microdistricts):
                self._session.delete(um)
            for md_id in body.microdistrictIds:
                self._session.add(m.UserMicrodistrict(user_id=row.id, microdistrict_id=md_id))
        if body.streetIds is not None:
            for us in list(row.streets):
                self._session.delete(us)
            for st_code in body.streetIds:
                st_uid = self._resolve_uuid(m.Street, st_code)
                if st_uid is not None:
                    self._session.add(m.UserStreet(user_id=row.id, street_id=st_uid))
        if body.resetPassword:
            from app.passwords import hash_password

            row.status = AccountStatus.active
            plain = random_temp_password()
            row.password_hash = hash_password(plain)
            creds = Credentials(login=row.login or "", tempPassword=plain)
        self._session.flush()
        return self._map_user(row), creds

    def delete_user(self, uid_str: str) -> User | None:
        """Hard-delete user account. Owner.owner_user_id → SET NULL via FK."""
        uid = self._resolve_uuid(m.AppUser, uid_str)
        row = self._session.get(m.AppUser, uid) if uid else None
        if row is None:
            return None
        self._ensure_same_region(row.region_id)
        if row.role in (Role.region_admin, Role.platform_superadmin):
            return None
        mapped = self._map_user(row)
        self._session.delete(row)
        self._session.flush()
        return mapped

    # ── reference ─────────────────────────────────────────────────
    def list_owners(self, owner_user_id: str | None = None) -> list[Owner]:
        q = select(m.Owner)
        if self._region_id:
            q = q.where(m.Owner.region_id == self._region_id)
        if owner_user_id:
            uid = self._resolve_uuid(m.AppUser, owner_user_id)
            if uid is None:
                return []
            q = q.where(m.Owner.owner_user_id == uid)
        return [self._owner_dto(r) for r in self._session.scalars(q).all()]

    def find_owner(self, wid: str) -> Owner | None:
        uid = self._resolve_uuid(m.Owner, wid)
        row = self._session.get(m.Owner, uid) if uid else None
        if row is None:
            return None
        self._ensure_same_region(row.region_id)
        return self._owner_dto(row)

    def create_owner(self, body: CreateOwnerRequest) -> Owner:
        region_id = self._region_id or "uralsk"
        account_uid = self._resolve_owner_account(body.ownerUserId, region_id=region_id)
        code = self.next_id("w")
        row = m.Owner(
            id=uuid_for_code(code),
            code=code,
            region_id=region_id,
            name=body.name,
            legal_form=body.legalForm,
            bin=body.bin,
            phone=body.phone,
            email=body.email,
            owner_user_id=account_uid,
        )
        self._session.add(row)
        self._session.flush()
        return self._owner_dto(row)

    def update_owner(self, wid: str, body: CreateOwnerRequest) -> Owner | None:
        uid = self._resolve_uuid(m.Owner, wid)
        row = self._session.get(m.Owner, uid) if uid else None
        if row is None:
            return None
        self._ensure_same_region(row.region_id)
        region_id = row.region_id or self._region_id or "uralsk"
        row.name = body.name
        row.legal_form = body.legalForm
        row.bin = body.bin
        row.phone = body.phone
        row.email = body.email
        # Preserve existing link unless caller explicitly sends ownerUserId
        # (including null to unlink).
        if "ownerUserId" in body.model_fields_set:
            row.owner_user_id = self._resolve_owner_account(
                body.ownerUserId, region_id=region_id
            )
        self._session.flush()
        return self._owner_dto(row)

    def list_districts(self) -> list[District]:
        q = select(m.District)
        if self._region_id:
            q = q.where(m.District.region_id == self._region_id)
        return [mappers.district(r) for r in self._session.scalars(q).all()]

    def create_district(self, body: DistrictCreate) -> District:
        code = self.next_id("d")
        region_id = self._region_id or "uralsk"
        if region_id != "uralsk":
            code = f"{region_id}-{code}"
        row = m.District(id=code, region_id=region_id, name=body.name)
        self._session.add(row)
        self._session.flush()
        return mappers.district(row)

    def list_microdistricts(self) -> list[Microdistrict]:
        q = select(m.Microdistrict)
        if self._region_id:
            q = q.where(m.Microdistrict.region_id == self._region_id)
        return [mappers.microdistrict(r) for r in self._session.scalars(q).all()]

    def first_microdistrict(self) -> Microdistrict:
        q = select(m.Microdistrict)
        if self._region_id:
            q = q.where(m.Microdistrict.region_id == self._region_id)
        row = self._session.scalar(q.limit(1))
        if row is None:
            raise LookupError("Нет микрорайонов в БД (нужен seed)")
        return mappers.microdistrict(row)

    def create_microdistrict(self, body: MicrodistrictCreate) -> Microdistrict:
        code = self.next_id("m")
        region_id = self._region_id or "uralsk"
        if region_id != "uralsk":
            code = f"{region_id}-{code}"
        row = m.Microdistrict(
            id=code, region_id=region_id, district_id=body.districtId, name=body.name
        )
        self._session.add(row)
        self._session.flush()
        return mappers.microdistrict(row)

    def list_object_types(self) -> list[str]:
        q = select(m.ObjectType.name)
        if self._region_id:
            q = q.where(m.ObjectType.region_id == self._region_id)
        return list(self._session.scalars(q).all())

    def add_object_type(self, type_name: str) -> list[str]:
        region_id = self._region_id or "uralsk"
        existing = self._session.scalar(
            select(m.ObjectType).where(
                m.ObjectType.name == type_name, m.ObjectType.region_id == region_id
            )
        )
        if not existing:
            self._session.add(
                m.ObjectType(
                    id=uuid_for_code(f"{region_id}:type:{type_name}"),
                    region_id=region_id,
                    name=type_name,
                )
            )
            self._session.flush()
        return self.list_object_types()

    def list_photos(self) -> list[Photo]:
        q = select(m.Photo)
        if self._region_id:
            q = q.join(m.CityObject, m.Photo.object_id == m.CityObject.id).where(
                m.CityObject.region_id == self._region_id
            )
        rows = self._session.scalars(q).all()
        return [mappers.photo(r, object_code=self._object_code(r.object_id)) for r in rows]

    def list_history(self) -> list[HistoryEvent]:
        # Скоуп по региону через объект: history_event.region_id нет, связь только
        # через object_id. Без join /audit отдавал журнал всех городов (утечка).
        q = select(m.HistoryEvent)
        if self._region_id:
            q = q.join(m.CityObject, m.HistoryEvent.object_id == m.CityObject.id).where(
                m.CityObject.region_id == self._region_id
            )
        rows = self._session.scalars(q).all()
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
        q = select(m.ObjectVersion)
        if self._region_id:
            q = q.join(m.CityObject, m.ObjectVersion.object_id == m.CityObject.id).where(
                m.CityObject.region_id == self._region_id
            )
        rows = self._session.scalars(q).all()
        return [mappers.object_version(r, object_code=self._object_code(r.object_id)) for r in rows]

    def inspection_trend(self) -> list[TrendPoint]:
        from app import config
        from app.domain_rules import inspection_trend_counts

        q = select(m.Inspection.date)
        if self._region_id:
            q = q.join(m.CityObject, m.Inspection.object_id == m.CityObject.id).where(
                m.CityObject.region_id == self._region_id
            )
        dates = list(self._session.scalars(q).all())
        return [
            TrendPoint(month=label, value=value)
            for label, value in inspection_trend_counts(dates, config.today_date())
        ]

    # ── checklist template / streets / geo ─────────────────────────
    def list_checklist_template(self, *, visible_only: bool = True) -> list[dto.ChecklistTemplateItem]:
        q = select(m.ChecklistTemplate)
        if self._region_id:
            q = q.where(m.ChecklistTemplate.region_id == self._region_id)
        if visible_only:
            q = q.where(m.ChecklistTemplate.is_visible.is_(True))
        q = q.order_by(m.ChecklistTemplate.sort_order, m.ChecklistTemplate.key)
        return [mappers.checklist_template(r) for r in self._session.scalars(q).all()]

    def manage_checklist_template(
        self, items: list[dto.ChecklistTemplateManageItem]
    ) -> list[dto.ChecklistTemplateItem]:
        region_id = self._region_id or "uralsk"
        for item in items:
            row = None
            if item.id:
                try:
                    uid = uuid.UUID(item.id)
                except ValueError:
                    uid = None
                if uid:
                    row = self._session.get(m.ChecklistTemplate, uid)
                    if row is not None:
                        self._ensure_same_region(row.region_id)
            if row is None:
                row = self._session.scalar(
                    select(m.ChecklistTemplate).where(
                        m.ChecklistTemplate.region_id == region_id,
                        m.ChecklistTemplate.key == item.key,
                    )
                )
            if row is None:
                row = m.ChecklistTemplate(
                    id=uuid.uuid4(),
                    region_id=region_id,
                    key=item.key,
                    title_ru=item.titleRu,
                    title_kz=item.titleKz,
                    category=item.category,
                    sort_order=item.sortOrder,
                    is_visible=item.isVisible,
                )
                self._session.add(row)
            else:
                row.key = item.key
                row.title_ru = item.titleRu
                row.title_kz = item.titleKz
                row.category = item.category
                row.sort_order = item.sortOrder
                row.is_visible = item.isVisible
        self._session.flush()
        return self.list_checklist_template(visible_only=False)

    def list_streets(self) -> list[dto.Street]:
        q = select(m.Street)
        if self._region_id:
            q = q.where(m.Street.region_id == self._region_id)
        q = q.order_by(m.Street.name)
        return [mappers.street(r) for r in self._session.scalars(q).all()]

    def create_street(self, body: dto.StreetCreate) -> dto.Street:
        region_id = self._region_id or "uralsk"
        code = self.next_id("st")
        if region_id != "uralsk":
            code = f"{region_id}-{code}"
        row = m.Street(
            id=uuid_for_code(code),
            code=code,
            region_id=region_id,
            name=body.name.strip(),
            district_id=body.districtId,
            microdistrict_id=body.microdistrictId,
        )
        self._session.add(row)
        self._session.flush()
        return mappers.street(row)

    def _street_row(self, sid: str) -> m.Street | None:
        uid = self._resolve_uuid(m.Street, sid)
        if uid is None:
            return None
        row = self._session.get(m.Street, uid)
        if row is None:
            return None
        self._ensure_same_region(row.region_id)
        return row

    def update_street(self, sid: str, body: dto.StreetPatch) -> dto.Street | None:
        row = self._street_row(sid)
        if row is None:
            return None
        data = body.model_dump(exclude_unset=True)
        if "name" in data and data["name"] is not None:
            row.name = data["name"].strip()
        if "districtId" in data:
            row.district_id = data["districtId"]
        if "microdistrictId" in data:
            row.microdistrict_id = data["microdistrictId"]
        self._session.flush()
        return mappers.street(row)

    def delete_street(self, sid: str) -> bool:
        row = self._street_row(sid)
        if row is None:
            return False
        self._session.delete(row)
        self._session.flush()
        return True

    def get_geo_config(self, city_id: str) -> dto.GeoConfig:
        from fastapi import HTTPException

        if self._region_id and city_id != self._region_id:
            raise HTTPException(
                status_code=403,
                detail={"message": "Нет доступа к данным другого города", "code": "forbidden"},
            )
        row = self._session.get(m.Region, city_id)
        if row is None:
            raise HTTPException(
                status_code=404,
                detail={"message": "Город не найден", "code": "not_found"},
            )
        return dto.GeoConfig(
            hasDistricts=row.has_districts,
            hasMicrodistricts=row.has_microdistricts,
            hasStreets=row.has_streets,
            addressSchema=row.address_schema or "microdistrict,street,house",
            cityType=row.city_type,
            oblast=row.oblast,
        )

    def update_geo_config(self, city_id: str, body: dto.GeoConfigPatch) -> dto.GeoConfig:
        from fastapi import HTTPException

        if self._region_id and city_id != self._region_id:
            raise HTTPException(
                status_code=403,
                detail={"message": "Нет доступа к данным другого города", "code": "forbidden"},
            )
        row = self._session.get(m.Region, city_id)
        if row is None:
            raise HTTPException(
                status_code=404,
                detail={"message": "Город не найден", "code": "not_found"},
            )
        data = body.model_dump(exclude_unset=True)
        mapping = {
            "hasDistricts": "has_districts",
            "hasMicrodistricts": "has_microdistricts",
            "hasStreets": "has_streets",
            "addressSchema": "address_schema",
            "cityType": "city_type",
            "oblast": "oblast",
        }
        for key, attr in mapping.items():
            if key in data:
                setattr(row, attr, data[key])
        self._session.flush()
        return self.get_geo_config(city_id)

    def get_current_city(self) -> dto.CurrentCity:
        from fastapi import HTTPException

        city_id = self._region_id
        if not city_id:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "У пользователя нет привязанного города",
                    "code": "no_region",
                },
            )
        row = self._session.get(m.Region, city_id)
        if row is None:
            raise HTTPException(
                status_code=404,
                detail={"message": "Город не найден", "code": "not_found"},
            )
        return dto.CurrentCity(
            id=row.id,
            name=row.name,
            code=row.code,
            hasDistricts=row.has_districts,
            hasMicrodistricts=row.has_microdistricts,
            hasStreets=row.has_streets,
            addressSchema=row.address_schema or "microdistrict,street,house",
            cityType=row.city_type,
            oblast=row.oblast,
        )
