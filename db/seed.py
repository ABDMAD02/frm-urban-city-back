"""Загрузка сид-данных из app/store.py в PostgreSQL (идемпотентно)."""
from __future__ import annotations

from datetime import date, timedelta

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
    SubscriptionPlan,
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


DEFAULT_REGION_ID = "uralsk"


def _ensure_plans(session: Session) -> None:
    plans = (
        (SubscriptionPlan.trial, "Trial", 10, 50, "Бесплатно"),
        (SubscriptionPlan.standard, "Standard", 50, 500, "По запросу"),
        (SubscriptionPlan.pro, "Pro", 200, 5000, "По запросу"),
    )
    existing_plans = set(session.scalars(select(m.Plan.id)).all())
    for plan_id, label, max_users, max_objects, price_hint in plans:
        if plan_id not in existing_plans:
            session.add(
                m.Plan(
                    id=plan_id,
                    label=label,
                    max_users=max_users,
                    max_objects=max_objects,
                    price_hint=price_hint,
                )
            )
    session.flush()


def _ensure_platform_superadmin(session: Session) -> None:
    """One platform login account; does not create regions or demo data."""
    existing = session.scalar(
        select(m.AppUser).where(
            (m.AppUser.login == PLATFORM_SUPERADMIN_LOGIN)
            | (m.AppUser.email == PLATFORM_SUPERADMIN_EMAIL)
            | (m.AppUser.code == "sa1")
            | (m.AppUser.role == Role.platform_superadmin)
        )
    )
    if existing is not None:
        if not existing.password_hash:
            existing.password_hash = hash_password(PLATFORM_SUPERADMIN_PASSWORD)
        if not existing.login:
            existing.login = PLATFORM_SUPERADMIN_LOGIN
        if not existing.email:
            existing.email = PLATFORM_SUPERADMIN_EMAIL
        session.flush()
        print("Platform superadmin already present")
        return

    session.add(
        m.AppUser(
            id=uuid_for_code("sa1"),
            code="sa1",
            name="Platform Superadmin",
            role=Role.platform_superadmin,
            position="Супер-администратор платформы",
            login=PLATFORM_SUPERADMIN_LOGIN,
            email=PLATFORM_SUPERADMIN_EMAIL,
            password_hash=hash_password(PLATFORM_SUPERADMIN_PASSWORD),
            status=AccountStatus.active,
            region_id=None,
            created_at=_parse_date("2026-05-01"),
        )
    )
    session.flush()
    print(f"Created platform superadmin login={PLATFORM_SUPERADMIN_LOGIN}")


def _ensure_platform_bootstrap(session: Session, region_id: str = DEFAULT_REGION_ID) -> None:
    """Plans + default region/subscription — only for demo seed path."""
    from sqlalchemy import text

    _ensure_plans(session)

    session.execute(
        text(
            """
            INSERT INTO region (id, code, name, status, timezone, locale, map_provider)
            VALUES (:id, :code, :name, 'active', 'Asia/Oral', 'ru', '2gis')
            ON CONFLICT (id) DO NOTHING
            """
        ),
        {"id": region_id, "code": region_id, "name": "Уральск"},
    )
    today = date.today()
    session.execute(
        text(
            """
            INSERT INTO subscription (
              region_id, plan, status, max_users, max_objects, valid_from, valid_until
            )
            VALUES (
              :region_id, 'standard', 'active', 50, 500, :valid_from, :valid_until
            )
            ON CONFLICT (region_id) DO NOTHING
            """
        ),
        {
            "region_id": region_id,
            "valid_from": today,
            "valid_until": today + timedelta(days=365),
        },
    )

    # Дизайн-код города. На пустой базе миграция 0005 его пропускает — региона
    # там ещё не существует, — поэтому засеваем здесь, после создания региона.
    from app.address import DEFAULT_CHECKLIST_ITEMS

    for item in DEFAULT_CHECKLIST_ITEMS:
        session.execute(
            text(
                """
                INSERT INTO checklist_template (
                  id, region_id, key, title_ru, title_kz, category, sort_order, is_visible
                )
                VALUES (
                  gen_random_uuid(), :region_id, :key, :title_ru, :title_kz,
                  :category, :sort_order, true
                )
                ON CONFLICT (region_id, key) DO NOTHING
                """
            ),
            {"region_id": region_id, **item},
        )
    session.flush()


def run_platform_bootstrap(session: Session) -> None:
    """Minimal bootstrap: plan catalog + platform superadmin. Tenant tables stay empty."""
    _backfill_password_hashes(session)
    _ensure_plans(session)
    _ensure_platform_superadmin(session)


def run_platform_bootstrap_cli() -> None:
    from db.base import SessionLocal, get_engine

    get_engine()
    with SessionLocal() as session:
        run_platform_bootstrap(session)
        session.commit()
        print("Platform bootstrap completed.")


def run_seed(session: Session) -> None:
    _backfill_password_hashes(session)
    _ensure_platform_bootstrap(session)
    _ensure_platform_superadmin(session)
    if is_seeded(session):
        print("Seed skipped: city_object already has rows")
        return

    # Справочники — идемпотентно (после прошлых частичных ошибок).
    region_id = DEFAULT_REGION_ID
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
    all_users = list(session.scalars(select(m.AppUser)).all())
    by_code = {row.code: row for row in all_users if row.code}
    by_login = {(row.login or "").lower(): row for row in all_users if row.login}
    by_email = {(row.email or "").lower(): row for row in all_users if row.email}

    def _find_existing_user(u) -> m.AppUser | None:
        if u.id in by_code:
            return by_code[u.id]
        if u.login and u.login.lower() in by_login:
            return by_login[u.login.lower()]
        if u.email and u.email.lower() in by_email:
            return by_email[u.email.lower()]
        if u.role.value == "platform_superadmin":
            for row in all_users:
                if row.role == Role.platform_superadmin:
                    return row
        return None

    existing_umds = {
        (row.user_id, row.microdistrict_id)
        for row in session.scalars(select(m.UserMicrodistrict)).all()
    }
    for u in seed.USERS:
        found = _find_existing_user(u)
        if found is not None:
            # Align public code/login for users created by migration with a different code.
            if not found.code:
                found.code = u.id
            if u.login and not found.login:
                found.login = u.login
            if u.email and not found.email:
                found.email = u.email
            if not found.password_hash:
                found.password_hash = hash_password(
                    PLATFORM_SUPERADMIN_PASSWORD
                    if u.role.value == "platform_superadmin"
                    else temp_password(u.id)
                )
            user_uuid[u.id] = found
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
        if u.login:
            by_login[u.login.lower()] = row
        if u.email:
            by_email[u.email.lower()] = row
        by_code[u.id] = row
        if u.microdistrictIds:
            for md_id in u.microdistrictIds:
                key = (row.id, md_id)
                if key not in existing_umds:
                    session.add(m.UserMicrodistrict(user_id=row.id, microdistrict_id=md_id))
                    existing_umds.add(key)
    session.flush()

    # Attach microdistricts for pre-existing users (e.g. after partial seed).
    for u in seed.USERS:
        row = user_uuid.get(u.id)
        if not row or not u.microdistrictIds:
            continue
        for md_id in u.microdistrictIds:
            key = (row.id, md_id)
            if key not in existing_umds:
                session.add(m.UserMicrodistrict(user_id=row.id, microdistrict_id=md_id))
                existing_umds.add(key)
    session.flush()

    # Owner.owner_user_id: account → many businesses (per seed ownerUserId).
    for o in seed.OWNERS:
        if not o.ownerUserId:
            continue
        owner_row = owner_uuid.get(o.id)
        user_row = user_uuid.get(o.ownerUserId)
        if owner_row is not None and user_row is not None:
            owner_row.owner_user_id = user_row.id
    session.flush()

    object_uuid: dict[str, m.CityObject] = {}
    existing_objects = {
        row.code: row
        for row in session.scalars(select(m.CityObject).where(m.CityObject.code.is_not(None))).all()
    }
    for o in seed.OBJECTS:
        if o.id in existing_objects:
            object_uuid[o.id] = existing_objects[o.id]
            continue
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
    existing_photos = {
        row.code: row
        for row in session.scalars(select(m.Photo).where(m.Photo.code.is_not(None))).all()
    }
    photo_objects = {"p1": "o5", "p2": "o5", "p3": "o12", "p4": "o1", "p5": "o12", "p6": "o12"}
    for p in seed.PHOTOS:
        if p.id in existing_photos:
            photo_uuid[p.id] = existing_photos[p.id]
            continue
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
    existing_inspections = {
        row.code: row
        for row in session.scalars(select(m.Inspection).where(m.Inspection.code.is_not(None))).all()
    }
    for insp in seed.INSPECTIONS:
        if insp.id in existing_inspections:
            inspection_uuid[insp.id] = existing_inspections[insp.id]
            continue
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

    existing_prescriptions = {
        row.code
        for row in session.scalars(select(m.Prescription).where(m.Prescription.code.is_not(None))).all()
    }
    for pr in seed.PRESCRIPTIONS:
        if pr.id in existing_prescriptions:
            continue
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

    existing_history = {
        row.code
        for row in session.scalars(select(m.HistoryEvent).where(m.HistoryEvent.code.is_not(None))).all()
    }
    for h in seed.HISTORY:
        if h.id in existing_history:
            continue
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

    existing_versions = {
        row.code
        for row in session.scalars(select(m.ObjectVersion).where(m.ObjectVersion.code.is_not(None))).all()
    }
    for v in seed.VERSIONS:
        if v.id in existing_versions:
            continue
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
