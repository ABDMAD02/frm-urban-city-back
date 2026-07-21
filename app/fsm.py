"""Статусная машина объекта — зеркало frontend/src/domain/status.ts.
Это доменный инвариант: сервер обязан валидировать переход, а не доверять клиенту."""
from .enums import ObjectStatus as S

ALLOWED_TRANSITIONS: dict[S, list[S]] = {
    S.new: [S.not_inspected, S.archived],
    S.not_inspected: [S.compliant, S.has_remarks, S.archived],
    S.compliant: [S.closed, S.has_remarks, S.archived],
    S.has_remarks: [S.prescription_issued, S.archived],
    S.prescription_issued: [S.awaiting_reinspection, S.archived],
    S.awaiting_reinspection: [S.violation_fixed, S.prescription_issued, S.archived],
    S.violation_fixed: [S.closed, S.archived],
    S.closed: [S.archived],
    S.archived: [],
}


def can_transition(frm: S, to: S) -> bool:
    if frm == to:
        return True
    return to in ALLOWED_TRANSITIONS[frm]


# Чек-лист дизайн-кода (12 пунктов) — зеркало CHECKLIST_TEMPLATE.
CHECKLIST_TEMPLATE = [
    {"key": "facade", "label": "Фасад"},
    {"key": "signboard", "label": "Вывеска"},
    {"key": "ads", "label": "Рекламные конструкции"},
    {"key": "banners", "label": "Баннеры"},
    {"key": "led", "label": "LED-экраны"},
    {"key": "entrance", "label": "Входная группа"},
    {"key": "arch_style", "label": "Архитектурный стиль"},
    {"key": "lighting", "label": "Освещение"},
    {"key": "improvement", "label": "Благоустройство"},
    {"key": "greenery", "label": "Озеленение"},
    {"key": "design_code", "label": "Соответствие дизайн-коду"},
    {"key": "cleanliness", "label": "Чистота прилегающей территории"},
]
