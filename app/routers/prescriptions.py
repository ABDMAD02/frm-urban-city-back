"""Предписания: чтение, ручная правка (закрыть/продлить), отправка по email."""
from fastapi import APIRouter, Depends, HTTPException

from .. import config
from ..deps import StoreDep
from ..security import get_current_user
from ..models import (
    Prescription, PrescriptionPatch, SendPrescriptionRequest, SendResult, HistoryEvent, User,
)
from ..enums import HistoryType

router = APIRouter(tags=["Предписания"])


@router.get("/prescriptions", response_model=list[Prescription], summary="Список предписаний")
def list_prescriptions(repo: StoreDep, user: User = Depends(get_current_user)):
    return repo.list_prescriptions()


@router.get("/prescriptions/{pid}", response_model=Prescription, summary="Одно предписание")
def get_prescription(pid: str, repo: StoreDep, user: User = Depends(get_current_user)):
    pr = repo.find_prescription(pid)
    if pr is None:
        raise HTTPException(404, "Предписание не найдено")
    return pr


@router.patch("/prescriptions/{pid}", response_model=Prescription, summary="Изменить предписание")
def patch_prescription(pid: str, body: PrescriptionPatch, repo: StoreDep, user: User = Depends(get_current_user)):
    pr = repo.patch_prescription(pid, body.model_dump(exclude_none=True))
    if pr is None:
        raise HTTPException(404, "Предписание не найдено")
    return pr


@router.post("/prescriptions/{pid}/send", response_model=SendResult, summary="Отправить по email")
def send_prescription(pid: str, body: SendPrescriptionRequest, repo: StoreDep, user: User = Depends(get_current_user)):
    pr = repo.find_prescription(pid)
    if pr is None:
        raise HTTPException(404, "Предписание не найдено")
    obj = repo.find_object(pr.objectId)
    owner = repo.find_owner(obj.ownerId) if obj else None
    to = body.email or (owner.email if owner else None)
    repo.append_history(HistoryEvent(
        id="", objectId=pr.objectId, type=HistoryType.prescription_issued,
        actor=user.name, date=config.DEMO_TODAY,
        text=f"Предписание отправлено ответственному лицу{(' (' + to + ')') if to else ''}",
    ))
    return SendResult(sent=True, sentAt=config.DEMO_TODAY + "T09:00:00Z", to=to)
