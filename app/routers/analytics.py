"""Аналитика — серверный расчёт KPI и разрезов (порт domain/analytics.ts)."""
from fastapi import APIRouter, Depends

from ..deps import StoreDep
from ..security import get_current_user
from ..models import TrendPoint, KpiSummary, DistrictStat, User
from ..enums import ObjectStatus, PrescriptionStatus

router = APIRouter(tags=["Аналитика"])

_VIOLATION = {ObjectStatus.has_remarks, ObjectStatus.prescription_issued, ObjectStatus.awaiting_reinspection}


@router.get("/analytics/inspection-trend", response_model=list[TrendPoint], summary="Динамика проверок")
def inspection_trend(repo: StoreDep, user: User = Depends(get_current_user)):
    return repo.inspection_trend()


@router.get("/analytics/summary", response_model=KpiSummary, summary="Сводные KPI")
def summary(repo: StoreDep, user: User = Depends(get_current_user)):
    objs = repo.list_objects()
    total = len(objs)
    inspections = len(repo.list_inspections())
    violations = sum(1 for o in objs if o.status in _VIOLATION)
    compliant = sum(1 for o in objs if o.status == ObjectStatus.compliant)
    overdue = sum(1 for p in repo.list_prescriptions() if p.status == PrescriptionStatus.overdue)
    fixed = sum(1 for o in objs if o.status == ObjectStatus.violation_fixed)
    inspected = sum(1 for o in objs if o.status not in (ObjectStatus.new, ObjectStatus.not_inspected))
    return KpiSummary(
        total=total, inspections=inspections, violations=violations, compliant=compliant,
        overdue=overdue, fixed=fixed,
        inspectedPct=round(inspected / total * 100, 1) if total else 0,
        compliantPct=round(compliant / total * 100, 1) if total else 0,
    )


@router.get("/analytics/by-district", response_model=list[DistrictStat], summary="Разрез по районам")
def by_district(repo: StoreDep, user: User = Depends(get_current_user)):
    out = []
    for d in repo.list_districts():
        objs = [o for o in repo.list_objects() if o.districtId == d.id]
        out.append(DistrictStat(
            districtId=d.id, name=d.name, total=len(objs),
            violations=sum(1 for o in objs if o.status in _VIOLATION),
            compliant=sum(1 for o in objs if o.status == ObjectStatus.compliant),
        ))
    return out


@router.get("/analytics/status-distribution", response_model=dict[str, int], summary="Распределение по статусам")
def status_distribution(repo: StoreDep, user: User = Depends(get_current_user)):
    dist: dict[str, int] = {}
    for o in repo.list_objects():
        dist[o.status.value] = dist.get(o.status.value, 0) + 1
    return dist
