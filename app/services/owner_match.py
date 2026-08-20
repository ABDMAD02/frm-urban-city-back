"""Подбор кандидатов-владельцев для объекта по схожести названия.

У объекта из OSM нет БИН/владельца, у бизнеса из egov нет координат — связать
их полностью автоматом нельзя. Поэтому подбираем КАНДИДАТОВ по нормализованному
названию (убираем ОПФ и типы заведений), а финальную привязку подтверждает
урбанист в UI (полу-ручной матчинг).
"""
from __future__ import annotations

import re

# Технический владелец города (объекты без установленного собственника).
PLACEHOLDER_OWNER_NAME = "Собственник не установлен"

# Слова-шумы: организационно-правовые формы + типы заведений.
_STOP = {
    "тоо", "ип", "ао", "оао", "зао", "пао", "нао", "гу", "кгп", "тд",
    "товарищество", "с", "ограниченной", "ответственностью",
    "индивидуальный", "предприниматель", "фирма", "компания", "группа",
    "кафе", "ресторан", "магазин", "аптека", "бар", "паб", "салон", "красоты",
    "гостиница", "отель", "маркет", "супермаркет", "мини", "центр", "фитнес",
    "клиника", "банк", "азс", "кинотеатр", "рынок", "фастфуд", "объект",
}


def _tokens(name: str | None) -> set[str]:
    s = (name or "").lower().replace("ё", "е")
    s = re.sub(r"[^\w\s]", " ", s, flags=re.UNICODE)
    return {t for t in s.split() if len(t) > 1 and t not in _STOP}


def score(a_name: str, b_name: str) -> float:
    """Похожесть названий: Жаккар по значимым токенам (0..1)."""
    a, b = _tokens(a_name), _tokens(b_name)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def candidates(obj_name: str, owners, *, exclude_names=(), limit: int = 5):
    """Список владельцев, чьё название пересекается с названием объекта (по убыванию похожести)."""
    exclude = set(exclude_names) | {PLACEHOLDER_OWNER_NAME}
    scored = [(score(obj_name, o.name), o) for o in owners if o.name not in exclude]
    scored = [(s, o) for s, o in scored if s > 0]
    scored.sort(key=lambda x: -x[0])
    return [o for _, o in scored[:limit]]
