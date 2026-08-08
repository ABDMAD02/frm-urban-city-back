"""Доменные правила, не привязанные к хранилищу и к HTTP.

Чистые функции: одинаковый результат в memory- и db-реализациях, тестируются
без БД и без сервера.
"""
from __future__ import annotations

from .enums import PrescriptionStatus


def effective_prescription_status(
    stored: PrescriptionStatus, deadline: str, today: str
) -> PrescriptionStatus:
    """«По истечении срока — просрочено».

    Открытое уведомление с прошедшим дедлайном считается просроченным. Статус не
    хранится как overdue (его никто не пересчитывал — из-за этого срок никогда не
    истекал, а эскалация в налоговую не запускалась), а выводится на чтение.
    Даты в формате ISO (YYYY-MM-DD) сравниваются лексикографически.
    """
    if stored == PrescriptionStatus.open and deadline and today and deadline < today:
        return PrescriptionStatus.overdue
    return stored
