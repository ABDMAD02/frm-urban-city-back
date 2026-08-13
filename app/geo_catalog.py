"""Глобальный каталог географии городов РК (сид для провижна региона).

Данные используются in-memory режимом напрямую; в PostgreSQL заливаются миграцией 0009.
"""
from __future__ import annotations

from typing import Any

# Формат: city → config + иерархия districts → microdistricts, streets (flat per city)
GEO_CATALOG_CITIES: list[dict[str, Any]] = [
    {
        "id": "kz-uralsk",
        "name": "Уральск",
        "oblast": "ЗКО",
        "config": {
            "hasDistricts": True,
            "hasMicrodistricts": True,
            "hasStreets": True,
            "addressSchema": "microdistrict,street,house",
            "cityType": "city",
            "centerLat": 51.2277,
            "centerLng": 51.3865,
            "mapZoom": 12,
        },
        "districts": [
            {
                "name": "Центральный район",
                "microdistricts": ["мкр. Астана", "мкр. Женис", "мкр. Кунаева"],
                "streets": ["пр. Абулхаир хана", "ул. Достык-Дружба", "ул. Курмангазы"],
            },
            {
                "name": "Зачаганск",
                "microdistricts": ["мкр. Строитель", "мкр. Сарыарка"],
                "streets": ["ул. Сарайшык", "ул. Ихсанова"],
            },
            {
                "name": "Затон",
                "microdistricts": ["мкр. Атамекен", "мкр. Мирлан"],
                "streets": ["пр. Евразия", "ул. Ментешева", "ул. Жангир хана"],
            },
        ],
    },
    {
        "id": "kz-aktau",
        "name": "Актау",
        "oblast": "mangystau",
        "config": {
            "hasDistricts": True,
            "hasMicrodistricts": True,
            "hasStreets": True,
            "addressSchema": "microdistrict,street,house",
            "cityType": "city",
            "centerLat": 43.65,
            "centerLng": 51.16,
            "mapZoom": 12,
        },
        "districts": [
            {
                "name": "1-й микрорайон",
                "microdistricts": ["мкр. 1", "мкр. 2", "мкр. 3"],
                "streets": ["пр. Абая", "ул. 15-й", "ул. 23-й"],
            },
            {
                "name": "2-й микрорайон",
                "microdistricts": ["мкр. 4", "мкр. 5"],
                "streets": ["ул. 2-й", "ул. 4-й", "ул. 6-й"],
            },
        ],
    },
]


def catalog_by_id(city_id: str) -> dict[str, Any] | None:
    return next((c for c in GEO_CATALOG_CITIES if c["id"] == city_id), None)


def catalog_city_summary(city: dict[str, Any]) -> dict[str, Any]:
    districts = city.get("districts") or []
    md_count = sum(len(d.get("microdistricts") or []) for d in districts)
    st_count = sum(len(d.get("streets") or []) for d in districts)
    return {
        "id": city["id"],
        "name": city["name"],
        "oblast": city.get("oblast"),
        "districts": len(districts),
        "microdistricts": md_count,
        "streets": st_count,
    }
