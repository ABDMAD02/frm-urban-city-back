"""Перечисления предметной области — зеркало frontend/src/domain/entities.ts."""
from enum import Enum


class Role(str, Enum):
    urbanist = "urbanist"
    owner = "owner"
    region_admin = "region_admin"


class AccountStatus(str, Enum):
    active = "active"
    blocked = "blocked"


class ObjectStatus(str, Enum):
    new = "new"
    not_inspected = "not_inspected"
    compliant = "compliant"
    has_remarks = "has_remarks"
    prescription_issued = "prescription_issued"
    awaiting_reinspection = "awaiting_reinspection"
    violation_fixed = "violation_fixed"
    closed = "closed"
    archived = "archived"


class InspectionResult(str, Enum):
    compliant = "compliant"
    has_remarks = "has_remarks"


class ReinspectionResult(str, Enum):
    fixed = "fixed"
    partial = "partial"
    not_fixed = "not_fixed"


class PrescriptionStatus(str, Enum):
    open = "open"
    overdue = "overdue"
    fixed = "fixed"
    closed = "closed"


class LegalForm(str, Enum):
    ip = "ИП"
    too = "ТОО"
    fizlico = "Физлицо"
    gosorgan = "Госорган"


class ChecklistValue(str, Enum):
    ok = "ok"
    issue = "issue"
    na = "na"


class PhotoKind(str, Enum):
    before = "before"
    after = "after"
    general = "general"


class HistoryType(str, Enum):
    object_created = "object_created"
    card_updated = "card_updated"
    owner_changed = "owner_changed"
    inspection_done = "inspection_done"
    prescription_issued = "prescription_issued"
    photos_uploaded = "photos_uploaded"
    violation_fixed = "violation_fixed"
    reinspection = "reinspection"
    status_changed = "status_changed"
    archived = "archived"
