"""Аналитика — серверный расчёт KPI и разрезов (порт domain/analytics.ts)."""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from ..deps import StoreDep
from ..security import accessible_object_ids, get_current_user, require_operator, require_region_admin
from ..models import (
    TrendPoint, KpiSummary, DistrictStat, User, CityObject,
    UnassignedObject, UrbanistActivityItem, UrbanistActivityResponse, MyOutputResponse,
)
from ..enums import ObjectStatus, PrescriptionStatus, Role

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
    if user.role == Role.owner:
        return []
    if user.role == Role.urbanist:
        # Урбанист видит тренд только по своим объектам (зонам).
        allowed = accessible_object_ids(repo, user)
        return repo.inspection_trend(object_ids=allowed)
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


@router.get(
    "/analytics/unassigned-objects",
    response_model=list[UnassignedObject],
    summary="Объекты без назначения или без проверки (скоуп региона)",
)
def unassigned_objects(repo: StoreDep, user: User = Depends(require_region_admin)):
    all_objects = [o for o in repo.list_objects() if o.status != ObjectStatus.archived]
    inspected_ids = {i.objectId for i in repo.list_inspections()}
    result: list[UnassignedObject] = []
    for o in all_objects:
        if o.assignedUrbanistId is None and o.microdistrictId is None and o.streetId is None:
            result.append(UnassignedObject(objectId=o.id, name=o.name, reason="not_assigned"))
        elif o.id not in inspected_ids and o.status in (ObjectStatus.new, ObjectStatus.not_inspected):
            result.append(UnassignedObject(objectId=o.id, name=o.name, reason="not_inspected"))
    return result


def _parse_date(s: str, param: str) -> date:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(400, detail={"message": f"Параметр {param!r} должен быть в формате YYYY-MM-DD", "code": "bad_request"})


@router.get(
    "/analytics/urbanist-activity",
    response_model=UrbanistActivityResponse,
    summary="Активность урбанистов за период (скоуп региона)",
)
def urbanist_activity(
    repo: StoreDep,
    user: User = Depends(require_region_admin),
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
):
    from_date = _parse_date(from_, "from") if from_ else None
    to_date = _parse_date(to, "to") if to else None
    if from_date and to_date and from_date > to_date:
        raise HTTPException(400, detail={"message": "Параметр 'from' не может быть позже 'to'", "code": "bad_request"})

    urbanists = [u for u in repo.list_users() if u.role == Role.urbanist]
    all_inspections = repo.list_inspections()

    def _in_range(insp_date: str) -> bool:
        try:
            d = datetime.strptime(insp_date, "%Y-%m-%d").date()
        except ValueError:
            return True
        if from_date and d < from_date:
            return False
        if to_date and d > to_date:
            return False
        return True

    items: list[UrbanistActivityItem] = []
    for u in urbanists:
        mine = [i for i in all_inspections if i.inspectorId == u.id and _in_range(i.date)]
        last_at = max((i.date for i in mine), default=None)
        items.append(UrbanistActivityItem(
            urbanistId=u.id,
            name=u.name,
            inspections=len(mine),
            lastAt=last_at,
        ))

    period = {
        "from": str(from_date) if from_date else "",
        "to": str(to_date) if to_date else "",
    }
    return UrbanistActivityResponse(dataReady=True, period=period, items=items)


@router.get(
    "/analytics/my-output",
    response_model=MyOutputResponse,
    summary="Личная выработка урбаниста за период",
)
def my_output(
    repo: StoreDep,
    user: User = Depends(require_operator),
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
):
    from_date = _parse_date(from_, "from") if from_ else None
    to_date = _parse_date(to, "to") if to else None
    if from_date and to_date and from_date > to_date:
        raise HTTPException(400, detail={"message": "Параметр 'from' не может быть позже 'to'", "code": "bad_request"})

    all_inspections = repo.list_inspections()
    count = 0
    for i in all_inspections:
        if i.inspectorId != user.id:
            continue
        try:
            d = datetime.strptime(i.date, "%Y-%m-%d").date()
        except ValueError:
            d = None
        if from_date and d is not None and d < from_date:
            continue
        if to_date and d is not None and d > to_date:
            continue
        count += 1

    period = {
        "from": str(from_date) if from_date else "",
        "to": str(to_date) if to_date else "",
    }
    return MyOutputResponse(inspections=count, period=period)
