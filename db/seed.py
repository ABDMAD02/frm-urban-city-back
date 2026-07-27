"""Загрузка сид-данных из app/store.py в PostgreSQL (идемпотентно)."""
from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import store as seed
from app.passwords import hash_password
from app.user_helpers import (
    PLATFORM_SUPERADMIN_EMAIL,
    PLATFORM_SUPERADMIN_LOGIN,
    PLATFORM_SUPERADMIN_PASSWORD,
    temp_password,
)
from db.enums import (
    AccountStatus,
    ChecklistValue,
    HistoryType,
    InspectionResult,
    LegalForm,
    ObjectStatus,
    PhotoKind,
    PrescriptionStatus,
    Role,
)
from db.codes import uuid_for_code
from db import models as m


def _parse_date(s: str) -> date:
    y, mo, d = s.split("-")
    return date(int(y), int(mo), int(d))


def is_seeded(session: Session) -> bool:
    return session.scalar(select(func.count()).select_from(m.CityObject)) > 0


def _backfill_password_hashes(session: Session) -> None:
    """Проставить password_hash пользователям без хеша (идемпотентно)."""
    rows = session.scalars(select(m.AppUser).where(m.AppUser.password_hash.is_(None))).all()
    for row in rows:
        if row.role == Role.platform_superadmin:
            row.password_hash = hash_password(PLATFORM_SUPERADMIN_PASSWORD)
            if not row.login:
                row.login = PLATFORM_SUPERADMIN_LOGIN
            if not row.email:
                row.email = PLATFORM_SUPERADMIN_EMAIL
        elif row.code:
            row.password_hash = hash_password(temp_password(row.code))
    if rows:
        session.flush()
        print(f"Backfilled password_hash for {len(rows)} users")


def run_seed(session: Session) -> None:
    _backfill_password_hashes(session)
    if is_seeded(session):
        print("Seed skipped: city_object already has rows")
        return

    # Справочники — идемпотентно (после прошлых частичных ошибок).
    region_id = "uralsk"
    existing_districts = set(session.scalars(select(m.District.id)).all())
    for d in seed.DISTRICTS:
        if d.id not in existing_districts:
            session.add(m.District(id=d.id, region_id=region_id, name=d.name))
    session.flush()

    existing_mds = set(session.scalars(select(m.Microdistrict.id)).all())
    for md in seed.MICRODISTRICTS:
        if md.id not in existing_mds:
            session.add(
                m.Microdistrict(
                    id=md.id, region_id=region_id, district_id=md.districtId, name=md.name
                )
            )
    session.flush()

    existing_types = {
        row.name
        for row in session.scalars(
            select(m.ObjectType).where(m.ObjectType.region_id == region_id)
        ).all()
    }
    for t_name, t_cat in seed.TYPES:
        if t_name not in existing_types:
            session.add(
                m.ObjectType(
                    id=uuid_for_code(f"type:{t_name}"),
                    region_id=region_id,
                    name=t_name,
                    category=t_cat,
                )
            )
    session.flush()

    type_names = set(
        session.scalars(select(m.ObjectType.name).where(m.ObjectType.region_id == region_id)).all()
    )
    print(f"Seed object_type count={len(type_names)} sample={sorted(type_names)[:5]}")
    if "Магазин" not in type_names:
        raise RuntimeError(
            f"object_type seed failed: 'Магазин' missing after flush, have={sorted(type_names)}"
        )

    owner_uuid: dict[str, m.Owner] = {}
    existing_owners = {
        row.code: row
        for row in session.scalars(select(m.Owner).where(m.Owner.code.is_not(None))).all()
    }
    for o in seed.OWNERS:
        if o.id in existing_owners:
            owner_uuid[o.id] = existing_owners[o.id]
            continue
        row = m.Owner(
            id=uuid_for_code(o.id),
            code=o.id,
            region_id=region_id,
            name=o.name,
            legal_form=LegalForm(o.legalForm.value),
            bin=o.bin,
            phone=o.phone,
            email=o.email,
        )
        session.add(row)
        owner_uuid[o.id] = row
    session.flush()

    user_uuid: dict[str, m.AppUser] = {}
    existing_users = {
        row.code: row
        for row in session.scalars(select(m.AppUser).where(m.AppUser.code.is_not(None))).all()
    }
    for u in seed.USERS:
        if u.id in existing_users:
            user_uuid[u.id] = existing_users[u.id]
            continue
        owner_id = None
        if u.role.value == "owner" and u.ownerObjectIds:
            owner_id = owner_uuid["w2"].id
        row = m.AppUser(
            id=uuid_for_code(u.id),
            code=u.id,
            name=u.name,
            role=Role(u.role.value),
            position=u.position,
            login=u.login,
            email=u.email,
            password_hash=hash_password(
                PLATFORM_SUPERADMIN_PASSWORD
                if u.role.value == "platform_superadmin"
                else temp_password(u.id)
            ),
            status=AccountStatus(u.status.value) if u.status else AccountStatus.active,
            owner_id=owner_id,
            region_id=None if u.role.value == "platform_superadmin" else region_id,
            created_at=_parse_date(u.createdAt or "2026-05-01"),
        )
        session.add(row)
        user_uuid[u.id] = row
        if u.microdistrictIds:
            for md_id in u.microdistrictIds:
                session.add(m.UserMicrodistrict(user_id=row.id, microdistrict_id=md_id))
    session.flush()

    object_uuid: dict[str, m.CityObject] = {}
    for o in seed.OBJECTS:
        if o.type not in type_names:
            raise RuntimeError(f"object type {o.type!r} missing before city_object insert")
        row = m.CityObject(
            id=uuid_for_code(o.id),
            code=o.id,
            region_id=region_id,
            name=o.name,
            type=o.type,
            category=o.category,
            address=o.address,
            lat=o.lat,
            lng=o.lng,
            district_id=o.districtId,
            microdistrict_id=o.microdistrictId,
            street=o.street,
            owner_id=owner_uuid[o.ownerId].id,
            status=ObjectStatus(o.status.value),
            responsible=o.responsible,
            created_at=_parse_date(o.createdAt),
            updated_at=_parse_date(o.updatedAt),
        )
        session.add(row)
        object_uuid[o.id] = row
    session.flush()
    print(f"Seed city_object count={len(object_uuid)}")

    photo_uuid: dict[str, m.Photo] = {}
    photo_objects = {"p1": "o5", "p2": "o5", "p3": "o12", "p4": "o1", "p5": "o12", "p6": "o12"}
    for p in seed.PHOTOS:
        oid = photo_objects.get(p.id, "o1")
        row = m.Photo(
            id=uuid_for_code(p.id),
            code=p.id,
            object_id=object_uuid[oid].id,
            kind=PhotoKind(p.kind.value),
            caption=p.caption,
            color=p.color or None,
            url=p.url,
            date=_parse_date(p.date),
            author=p.author,
        )
        session.add(row)
        photo_uuid[p.id] = row

    inspection_uuid: dict[str, m.Inspection] = {}
    for insp in seed.INSPECTIONS:
        row = m.Inspection(
            id=uuid_for_code(insp.id),
            code=insp.id,
            object_id=object_uuid[insp.objectId].id,
            inspector=insp.inspector,
            date=_parse_date(insp.date),
            result=InspectionResult(insp.result.value),
            comment=insp.comment,
        )
        session.add(row)
        inspection_uuid[insp.id] = row
        for item in insp.checklist:
            session.add(
                m.ChecklistItem(
                    inspection_id=row.id,
                    key=item.key,
                    label=item.label,
                    value=ChecklistValue(item.value.value),
                    comment=item.comment,
                )
            )
        for pid in insp.photoIds:
            if pid in photo_uuid:
                photo_uuid[pid].inspection_id = row.id

    for pr in seed.PRESCRIPTIONS:
        session.add(
            m.Prescription(
                id=uuid_for_code(pr.id),
                code=pr.id,
                object_id=object_uuid[pr.objectId].id,
                inspection_id=inspection_uuid[pr.inspectionId].id,
                title=pr.title,
                description=pr.description,
                issued_at=_parse_date(pr.issuedAt),
                deadline=_parse_date(pr.deadline),
                reinspection_date=_parse_date(pr.reinspectionDate),
                status=PrescriptionStatus(pr.status.value),
            )
        )

    for h in seed.HISTORY:
        session.add(
            m.HistoryEvent(
                id=uuid_for_code(h.id),
                code=h.id,
                object_id=object_uuid[h.objectId].id,
                type=HistoryType(h.type.value),
                actor=h.actor,
                date=_parse_date(h.date),
                text=h.text,
            )
        )

    for v in seed.VERSIONS:
        session.add(
            m.ObjectVersion(
                id=uuid_for_code(v.id),
                code=v.id,
                object_id=object_uuid[v.objectId].id,
                date=_parse_date(v.date),
                author=v.author,
                label=v.label,
                changes=v.changes,
            )
        )

    session.flush()


def run_seed_cli() -> None:
    from db.base import SessionLocal, get_engine

    get_engine()
    with SessionLocal() as session:
        run_seed(session)
        session.commit()
        print("Seed completed.")


if __name__ == "__main__":
    run_seed_cli()
