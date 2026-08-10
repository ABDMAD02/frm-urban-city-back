"""Доменные правила, не привязанные к хранилищу и к HTTP.

Чистые функции: одинаковый результат в memory- и db-реализациях, тестируются
без БД и без сервера.
"""
from __future__ import annotations

from datetime import date

from .enums import PrescriptionStatus

_RU_MONTHS_SHORT = (
    "Янв", "Фев", "Мар", "Апр", "Май", "Июн",
    "Июл", "Авг", "Сен", "Окт", "Ноя", "Дек",
)


def inspection_trend_counts(
    dates: list[date], today: date, months: int = 6
) -> list[tuple[str, int]]:
    """Число проверок по месяцам за последние `months` месяцев, кончая текущим.

    Заменяет статический сид-массив: тренд считается из реальных дат проверок.
    Возвращает пары (короткая метка месяца, количество) в хронологическом порядке.
    """
    end_idx = today.year * 12 + (today.month - 1)
    buckets = [end_idx - k for k in range(months - 1, -1, -1)]
    counts = {b: 0 for b in buckets}
    for d in dates:
        idx = d.year * 12 + (d.month - 1)
        if idx in counts:
            counts[idx] += 1
    return [(_RU_MONTHS_SHORT[b % 12], counts[b]) for b in buckets]


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
