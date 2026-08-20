"""Предписания: чтение, ручная правка (закрыть/продлить), отправка по email."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import config
from ..deps import StoreDep
from ..security import (
    accessible_object_ids,
    ensure_owner_business_access,
    ensure_object_access,
    get_current_user,
    require_operator,
)
from ..models import (
    Prescription, PrescriptionPatch, SendPrescriptionRequest, SendResult, HistoryEvent, User,
)
from ..enums import HistoryType

router = APIRouter(tags=["Предписания"])


@router.get("/prescriptions", response_model=list[Prescription], summary="Список предписаний")
def list_prescriptions(
    repo: StoreDep,
    user: User = Depends(get_current_user),
    ownerId: Optional[str] = Query(None),
):
    items = repo.list_prescriptions()
    allowed = accessible_object_ids(repo, user)
    items = [p for p in items if p.objectId in allowed]
    if ownerId:
        ensure_owner_business_access(repo, user, ownerId)
        items = [
            p
            for p in items
            if (repo.find_object(p.objectId) and repo.find_object(p.objectId).ownerId == ownerId)
        ]
    return items


@router.get("/prescriptions/{pid}", response_model=Prescription, summary="Одно предписание")
def get_prescription(pid: str, repo: StoreDep, user: User = Depends(get_current_user)):
    pr = repo.find_prescription(pid)
    if pr is None:
        raise HTTPException(404, "Предписание не найдено")
    ensure_object_access(repo, user, pr.objectId)
    return pr


def _is_issue(c) -> bool:
    return str(c.value) == "issue" or str(getattr(c.value, "value", "")) == "issue"


def _document_data(pid: str, repo, user):
    """Сборка данных официального документа из БД (общая для HTML и PDF)."""
    pr = repo.find_prescription(pid)
    if pr is None:
        raise HTTPException(404, "Предписание не найдено")
    ensure_object_access(repo, user, pr.objectId)

    obj = repo.find_object(pr.objectId)
    owner = repo.find_owner(obj.ownerId) if obj and getattr(obj, "ownerId", None) else None

    template = {t.key: t.titleRu for t in repo.list_checklist_template(visible_only=False)}
    inspections = repo.list_inspections()
    insp = next((i for i in inspections if i.id == pr.inspectionId), None)
    if insp is None:
        insp = next((i for i in inspections
                     if i.objectId == pr.objectId and any(_is_issue(c) for c in i.checklist)), None)
    violations = [template.get(c.key, c.label) for c in insp.checklist if _is_issue(c)] if insp else []

    try:
        city = repo.get_current_city().name
    except Exception:
        city = ""
    return dict(city=city, presc=pr, obj=obj, owner=owner,
                violations=violations, inspector=(insp.inspector if insp else None))


@router.get("/prescriptions/{pid}/document", summary="Официальный документ предписания (HTML для печати)")
def prescription_document(pid: str, repo: StoreDep, user: User = Depends(get_current_user)):
    from fastapi.responses import HTMLResponse

    from ..services.prescription_doc import render_html

    return HTMLResponse(content=render_html(**_document_data(pid, repo, user)))


@router.get("/prescriptions/{pid}/document.pdf", summary="Официальный документ предписания (PDF)")
def prescription_document_pdf(pid: str, repo: StoreDep, user: User = Depends(get_current_user)):
    from fastapi.responses import Response

    from ..services.prescription_doc import render_pdf

    pdf = render_pdf(**_document_data(pid, repo, user))
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="prescription-{pid}.pdf"'},
    )


@router.patch("/prescriptions/{pid}", response_model=Prescription, summary="Изменить предписание")
def patch_prescription(pid: str, body: PrescriptionPatch, repo: StoreDep, user: User = Depends(require_operator)):
    current = repo.find_prescription(pid)
    if current is None:
        raise HTTPException(404, "Предписание не найдено")
    ensure_object_access(repo, user, current.objectId)
    pr = repo.patch_prescription(pid, body.model_dump(exclude_none=True))
    if pr is None:
        raise HTTPException(404, "Предписание не найдено")
    return pr


@router.post("/prescriptions/{pid}/send", response_model=SendResult, summary="Отправить по email")
def send_prescription(pid: str, body: SendPrescriptionRequest, repo: StoreDep, user: User = Depends(require_operator)):
    pr = repo.find_prescription(pid)
    if pr is None:
        raise HTTPException(404, "Предписание не найдено")
    ensure_object_access(repo, user, pr.objectId)
    obj = repo.find_object(pr.objectId)
    owner = repo.find_owner(obj.ownerId) if obj else None
    to = body.email or (owner.email if owner else None)
    # Фиксируем выдачу уведомления (sent_at/sent_to). Реальной e-mail/Telegram
    # доставки пока нет — уведомление бумажное, выдаётся лично; здесь честно
    # фиксируется момент и адресат выдачи, а не факт электронной отправки.
    sent_at = repo.mark_prescription_sent(pid, to)
    repo.append_history(HistoryEvent(
        id="", objectId=pr.objectId, type=HistoryType.prescription_issued,
        actor=user.name, date=config.today_str(),
        text=f"Зафиксирована выдача уведомления ответственному лицу{(' (' + to + ')') if to else ''}",
    ))
    # sent=True означает «выдача зафиксирована», не «письмо доставлено».
    return SendResult(sent=True, sentAt=sent_at or config.now_iso(), to=to)
