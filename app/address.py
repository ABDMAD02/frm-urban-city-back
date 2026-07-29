"""Сборка адреса по address_schema региона."""
from __future__ import annotations


def build_address(
    *,
    address_schema: str,
    district_name: str | None = None,
    microdistrict_name: str | None = None,
    street_name: str | None = None,
    house: str | None = None,
    apartment: str | None = None,
) -> str:
    """Формирует адрес по схеме вида ``district,microdistrict,street,house,apartment``.

    Уральск (microdistrict,street,house): ``мкр. Астана, ул. Кунаева, 12``.
    """
    parts: list[str] = []
    for token in [t.strip() for t in (address_schema or "").split(",") if t.strip()]:
        if token == "district" and district_name:
            parts.append(district_name)
        elif token == "microdistrict" and microdistrict_name:
            name = microdistrict_name
            if not name.lower().startswith("мкр"):
                name = f"мкр. {name}"
            parts.append(name)
        elif token == "street" and street_name:
            name = street_name
            if not any(name.lower().startswith(p) for p in ("ул", "пр", "пер")):
                name = f"ул. {name}"
            parts.append(name)
        elif token == "house" and house:
            parts.append(str(house).strip())
        elif token == "apartment" and apartment:
            parts.append(f"кв. {str(apartment).strip()}")
    return ", ".join(parts) if parts else "—"


DEFAULT_CHECKLIST_ITEMS: list[dict] = [
    {
        "key": "facade",
        "title_ru": "Фасад",
        "title_kz": "Фасад",
        "category": "building",
        "sort_order": 1,
    },
    {
        "key": "signboard",
        "title_ru": "Вывеска",
        "title_kz": "Маңдайша",
        "category": "signage",
        "sort_order": 2,
    },
    {
        "key": "ads",
        "title_ru": "Реклама",
        "title_kz": "Жарнама",
        "category": "advertising",
        "sort_order": 3,
    },
    {
        "key": "banners",
        "title_ru": "Баннеры",
        "title_kz": "Баннерлер",
        "category": "advertising",
        "sort_order": 4,
    },
    {
        "key": "lighting",
        "title_ru": "Освещение",
        "title_kz": "Жарықтандыру",
        "category": "lighting",
        "sort_order": 5,
    },
    {
        "key": "materials",
        "title_ru": "Материалы",
        "title_kz": "Материалдар",
        "category": "materials",
        "sort_order": 6,
    },
]

DEFAULT_ADDRESS_SCHEMA = "microdistrict,street,house"
