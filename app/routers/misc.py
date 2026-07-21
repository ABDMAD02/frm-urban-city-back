"""Аудит и уведомления. Демо: аудит = лента истории, уведомления = просроченные предписания."""
from fastapi import APIRouter, Depends

from ..deps import StoreDep
from ..security import get_current_user
from ..models import HistoryEvent, Notification, User
from ..enums import PrescriptionStatus

router = APIRouter(tags=["Аудит и уведомления"])


@router.get("/audit", response_model=list[HistoryEvent], summary="Журнал действий")
def audit(repo: StoreDep, user: User = Depends(get_current_user)):
    return repo.list_history()


@router.get("/notifications", response_model=list[Notification], summary="Уведомления")
def notifications(repo: StoreDep, user: User = Depends(get_current_user)):
    out = []
    for p in repo.list_prescriptions():
        if p.status == PrescriptionStatus.overdue:
            out.append(Notification(
                id=f"n-{p.id}", type="prescription_overdue",
                text=f"Просрочено предписание: {p.title}", objectId=p.objectId,
                date=p.deadline, read=False,
            ))
    return out
