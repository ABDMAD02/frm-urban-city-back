"""Проверки и повторные проверки. Здесь живёт серверная бизнес-логика:
авто-создание предписания и пересчёт статуса объекта (порт domain/usecases.ts)."""
from fastapi import APIRouter, Depends, HTTPException

from .. import config
from ..deps import StoreDep
from ..security import accessible_object_ids, ensure_object_access, get_current_user, require_operator
from ..fsm import can_transition
from ..models import (
    Inspection, CreateInspectionRequest, InspectionResultView, ReinspectionRequest,
    CityObject, Prescription, HistoryEvent, User,
)
from ..enums import (
    ObjectStatus, InspectionResult, ReinspectionResult, PrescriptionStatus, HistoryType,
)

router = APIRouter(tags=["Проверки"])


def _persist_inspection_photos(
    repo: StoreDep,
    *,
    oid: str,
    insp_id: str,
    body: CreateInspectionRequest,
) -> list[str]:
    """Гарантирует строки Photo в сторе и возвращает итоговые photoIds."""
    saved_ids: list[str] = []
    seen: set[str] = set()

    for ph in body.photos:
        if not ph.objectId:
            ph.objectId = oid
        saved = repo.add_photo_if_missing(ph, object_id=oid, inspection_id=insp_id)
        if saved.id not in seen:
            saved_ids.append(saved.id)
            seen.add(saved.id)

    for pid in body.inspection.photoIds or []:
        if not pid or pid in seen:
            continue
        existing = repo.find_photo(pid)
        if existing is None:
            raise HTTPException(
                400,
                detail={
                    "message": f"Фото {pid} не найдено: сначала POST /photos или передайте объект в photos[]",
                    "code": "photo_not_found",
                },
            )
        linked = repo.add_photo_if_missing(existing, object_id=oid, inspection_id=insp_id)
        saved_ids.append(linked.id)
        seen.add(linked.id)

    if not saved_ids:
        raise HTTPException(
            400,
            detail={
                "message": "Фотофиксация обязательна: приложите минимум одно фото",
                "code": "bad_request",
            },
        )
    return saved_ids


@router.get("/inspections", response_model=list[Inspection], summary="Список проверок")
def list_inspections(repo: StoreDep, user: User = Depends(get_current_user)):
    items = repo.list_inspections()
    allowed = accessible_object_ids(repo, user)
    return [i for i in items if i.objectId in allowed]


@router.post("/objects/{oid}/inspections", response_model=InspectionResultView, status_code=201,
             summary="Провести первичную проверку")
def add_inspection(oid: str, body: CreateInspectionRequest, repo: StoreDep, user: User = Depends(require_operator)):
    obj = repo.find_object(oid)
    if obj is None:
        raise HTTPException(404, detail={"message": "Объект не найден", "code": "not_found"})
    ensure_object_access(repo, user, oid)
    if not body.photos and not (body.inspection.photoIds or []):
        raise HTTPException(
            400,
            detail={"message": "Фотофиксация обязательна: приложите минимум одно фото", "code": "bad_request"},
        )

    insp = body.inspection
    insp.objectId = oid
    # Сервер — источник истины: кто и когда провёл проверку, а не то, что прислал клиент.
    insp.inspector = user.name
    insp.inspectorId = user.id
    insp.date = config.today_str()
    repo.add_inspection(insp)
    insp.photoIds = _persist_inspection_photos(repo, oid=oid, insp_id=insp.id, body=body)
    # Memory store keeps photoIds on the Inspection object
    linked = repo.list_photos_for_inspection(insp.id)
    if linked:
        insp.photoIds = [p.id for p in linked]

    has_issues = insp.result == InspectionResult.has_remarks
    outcome = ObjectStatus.has_remarks if has_issues else ObjectStatus.compliant
    if not can_transition(obj.status, outcome):
        raise HTTPException(
            409,
            detail={
                "message": f"Недопустимый переход статуса: {obj.status.value} → {outcome.value}",
                "code": "conflict",
            },
        )
    obj = repo.set_object_status(oid, outcome)

    repo.append_history(HistoryEvent(
        id="", objectId=oid, type=HistoryType.inspection_done,
        actor=user.name, date=config.today_str(),
        text=body.note or ("Проведена проверка — выявлены замечания" if has_issues else "Проведена проверка — соответствует дизайн-коду"),
    ))

    prescription = None
    if has_issues:
        obj = repo.set_object_status(oid, ObjectStatus.prescription_issued)
        prescription = Prescription(
            id="", objectId=oid, inspectionId=insp.id,
            title="Устранение выявленных нарушений дизайн-кода",
            description=insp.comment or "Привести объект в соответствие с дизайн-кодом города.",
            issuedAt=config.today_str(),
            deadline=config.plus_days_str(config.PRESCRIPTION_DEADLINE_DAYS),
            reinspectionDate=config.plus_days_str(config.REINSPECTION_DELAY_DAYS),
            status=PrescriptionStatus.open,
        )
        prescription = repo.add_prescription(prescription)
        repo.append_history(HistoryEvent(
            id="", objectId=oid, type=HistoryType.prescription_issued,
            actor=user.name, date=config.today_str(), text="Выдано предписание",
        ))

    obj = repo.find_object(oid)
    return InspectionResultView(object=obj, inspection=insp, prescription=prescription)


_REINSPECT = {
    ReinspectionResult.fixed: (ObjectStatus.violation_fixed, "Повторная проверка: нарушение устранено"),
    ReinspectionResult.partial: (ObjectStatus.prescription_issued, "Повторная проверка: устранено частично — предписание продлено"),
    ReinspectionResult.not_fixed: (ObjectStatus.prescription_issued, "Повторная проверка: нарушение не устранено — предписание продлено"),
}


@router.post("/objects/{oid}/reinspections", response_model=CityObject, summary="Повторная проверка")
def reinspect(oid: str, body: ReinspectionRequest, repo: StoreDep, user: User = Depends(require_operator)):
    obj = repo.find_object(oid)
    if obj is None:
        raise HTTPException(404, detail={"message": "Объект не найден", "code": "not_found"})
    ensure_object_access(repo, user, oid)
    if obj.status == ObjectStatus.prescription_issued and can_transition(
        ObjectStatus.prescription_issued, ObjectStatus.awaiting_reinspection
    ):
        obj = repo.set_object_status(oid, ObjectStatus.awaiting_reinspection)
    target, note = _REINSPECT[body.result]
    if not can_transition(obj.status, target):
        raise HTTPException(
            409,
            detail={
                "message": f"Недопустимый переход статуса: {obj.status.value} → {target.value}",
                "code": "conflict",
            },
        )
    obj = repo.set_object_status(oid, target)

    # Обновляем связанное предписание объекта ПО-ПУНКТНО (не «тупо продлить»).
    presc = next(
        (p for p in repo.list_prescriptions()
         if p.objectId == oid and p.status in (PrescriptionStatus.open, PrescriptionStatus.overdue)),
        None,
    )
    total = len(body.fixed) + len(body.remaining)
    if total > 0:  # фронт прислал детализацию — собираем осмысленный лог + правим предписание
        if body.result == ReinspectionResult.fixed:
            note = f"Повторная проверка: все нарушения устранены ({len(body.fixed)}). Предписание закрыто."
            if presc:
                repo.patch_prescription(presc.id, {"status": PrescriptionStatus.fixed})
        else:
            new_deadline = config.plus_days_str(config.PRESCRIPTION_DEADLINE_DAYS)
            remaining_str = "; ".join(body.remaining) if body.remaining else "—"
            note = (f"Повторная проверка: устранено {len(body.fixed)} из {total}. "
                    f"Осталось: {remaining_str}. Предписание продлено до {new_deadline}.")
            if presc:
                patch = {"status": PrescriptionStatus.open, "deadline": new_deadline, "reinspectionDate": new_deadline}
                if body.remaining:
                    patch["description"] = f"Осталось устранить ({len(body.remaining)}): {remaining_str}."
                repo.patch_prescription(presc.id, patch)

    repo.append_history(HistoryEvent(
        id="", objectId=oid, type=HistoryType.reinspection,
        actor=user.name, date=config.today_str(), text=note,
    ))
    return obj
