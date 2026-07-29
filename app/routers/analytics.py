"""Аналитика — серверный расчёт KPI и разрезов (порт domain/analytics.ts)."""
from fastapi import APIRouter, Depends

from ..deps import StoreDep
from ..security import accessible_object_ids, get_current_user
from ..models import TrendPoint, KpiSummary, DistrictStat, User, CityObject
from ..enums import ObjectStatus, PrescriptionStatus

router = APIRouter(tags=["Аналитика"])

_VIOLATION = {ObjectStatus.has_remarks, ObjectStatus.prescription_issued, ObjectStatus.awaiting_reinspection}


def _scoped_objects(repo: StoreDep, user: User) -> list[CityObject]:
    allowed = accessible_object_ids(repo, user)
    return [
        o
        for o in repo.list_objects()
        if o.id in allowed and o.status != ObjectStatus.archived
    ]


@router.get("/analytics/inspection-trend", response_model=list[TrendPoint], summary="Динамика проверок")
def inspection_trend(repo: StoreDep, user: User = Depends(get_current_user)):
    # Seeded aggregate trend; only region-wide roles see it.
    if user.role.value == "owner":
        return []
    return repo.inspection_trend()


@router.get("/analytics/summary", response_model=KpiSummary, summary="Сводные KPI")
def summary(repo: StoreDep, user: User = Depends(get_current_user)):
    objs = _scoped_objects(repo, user)
    allowed = {o.id for o in objs}
    total = len(objs)
    inspections = sum(1 for i in repo.list_inspections() if i.objectId in allowed)
    violations = sum(1 for o in objs if o.status in _VIOLATION)
    compliant = sum(1 for o in objs if o.status == ObjectStatus.compliant)
    overdue = sum(
        1
        for p in repo.list_prescriptions()
        if p.status == PrescriptionStatus.overdue and p.objectId in allowed
    )
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
    objs = _scoped_objects(repo, user)
    out = []
    for d in repo.list_districts():
        district_objs = [o for o in objs if o.districtId == d.id]
        out.append(DistrictStat(
            districtId=d.id, name=d.name, total=len(district_objs),
            violations=sum(1 for o in district_objs if o.status in _VIOLATION),
            compliant=sum(1 for o in district_objs if o.status == ObjectStatus.compliant),
        ))
    return out


@router.get("/analytics/status-distribution", response_model=dict[str, int], summary="Распределение по статусам")
def status_distribution(repo: StoreDep, user: User = Depends(get_current_user)):
    dist: dict[str, int] = {}
    for o in _scoped_objects(repo, user):
        dist[o.status.value] = dist.get(o.status.value, 0) + 1
    return dist
