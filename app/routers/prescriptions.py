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


@router.patch("/prescriptions/{pid}", response_model=Prescription, summary="Изменить предписание")
def patch_prescription(pid: str, body: PrescriptionPatch, repo: StoreDep, user: User = Depends(get_current_user)):
    current = repo.find_prescription(pid)
    if current is None:
        raise HTTPException(404, "Предписание не найдено")
    ensure_object_access(repo, user, current.objectId)
    pr = repo.patch_prescription(pid, body.model_dump(exclude_none=True))
    if pr is None:
        raise HTTPException(404, "Предписание не найдено")
    return pr


@router.post("/prescriptions/{pid}/send", response_model=SendResult, summary="Отправить по email")
def send_prescription(pid: str, body: SendPrescriptionRequest, repo: StoreDep, user: User = Depends(get_current_user)):
    pr = repo.find_prescription(pid)
    if pr is None:
        raise HTTPException(404, "Предписание не найдено")
    ensure_object_access(repo, user, pr.objectId)
    obj = repo.find_object(pr.objectId)
    owner = repo.find_owner(obj.ownerId) if obj else None
    to = body.email or (owner.email if owner else None)
    repo.append_history(HistoryEvent(
        id="", objectId=pr.objectId, type=HistoryType.prescription_issued,
        actor=user.name, date=config.today_str(),
        text=f"Предписание отправлено ответственному лицу{(' (' + to + ')') if to else ''}",
    ))
    return SendResult(sent=True, sentAt=config.now_iso(), to=to)
