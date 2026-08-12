"""Аудит и уведомления. Демо: аудит = лента истории, уведомления = просроченные предписания."""
from fastapi import APIRouter, Depends

from .. import config
from ..deps import StoreDep
from ..domain_rules import effective_prescription_status
from ..security import accessible_object_ids, get_current_user, require_region_admin
from ..models import HistoryEvent, Notification, User
from ..enums import PrescriptionStatus

router = APIRouter(tags=["Аудит и уведомления"])


@router.get("/audit", response_model=list[HistoryEvent], summary="Журнал действий")
def audit(repo: StoreDep, user: User = Depends(require_region_admin)):
    return repo.list_history()


@router.get("/notifications", response_model=list[Notification], summary="Уведомления")
def notifications(repo: StoreDep, user: User = Depends(get_current_user)):
    allowed = accessible_object_ids(repo, user)
    today = config.today_str()
    out = []
    for p in repo.list_prescriptions():
        if p.objectId not in allowed:
            continue
        if effective_prescription_status(p.status, p.deadline, today) != PrescriptionStatus.overdue:
            continue
        out.append(Notification(
            id=f"n-{p.id}", type="prescription_overdue",
            text=f"Просрочено предписание: {p.title}", objectId=p.objectId,
            date=p.deadline, read=False,
        ))
    return out
