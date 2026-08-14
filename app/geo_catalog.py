"""Глобальный каталог городов РК (сид для провижна региона).

Из этого каталога суперадмин выбирает город при создании региона — код, название,
область, схема адреса и центр карты подставляются автоматически (без ручного ввода
кода → без опечаток). Детальная география (районы→микрорайоны→улицы) для большинства
городов заводится импортом файла per-region; у пилотов (Уральск, Актау) — демо-набор.

Данные используются in-memory режимом напрямую; в PostgreSQL заливаются миграциями
0009 (создание таблицы + первичный сид) и 0010 (доливка полного списка городов).
"""
from __future__ import annotations

from typing import Any

_DEFAULT_CONFIG = {
    "hasDistricts": True,
    "hasMicrodistricts": True,
    "hasStreets": True,
    "addressSchema": "microdistrict,street,house",
    "cityType": "city",
    "mapZoom": 12,
}


def _city(
    code: str,
    name: str,
    oblast: str,
    lat: float,
    lng: float,
    districts: list[dict[str, Any]] | None = None,
    *,
    city_type: str = "city",
) -> dict[str, Any]:
    """Город уровня «каталог»: код/имя/область/центр + пустая детальная гео."""
    return {
        "id": f"kz-{code}",
        "code": code,
        "name": name,
        "oblast": oblast,
        "config": {**_DEFAULT_CONFIG, "cityType": city_type, "centerLat": lat, "centerLng": lng},
        "districts": districts or [],
    }


# Формат: city → code + config + иерархия districts → microdistricts, streets.
# 3 города республиканского значения + 17 областных центров.
GEO_CATALOG_CITIES: list[dict[str, Any]] = [
    # ── Города республиканского значения ──
    _city("astana", "Астана", "Астана", 51.1605, 71.4704),
    _city("almaty", "Алматы", "Алматы", 43.2380, 76.9026),
    _city("shymkent", "Шымкент", "Шымкент", 42.3417, 69.5901),
    # ── Областные центры ──
    _city("kokshetau", "Кокшетау", "Акмолинская обл.", 53.2833, 69.3833),
    _city("aktobe", "Актобе", "Актюбинская обл.", 50.2839, 57.1670),
    _city("konaev", "Конаев", "Алматинская обл.", 43.8600, 77.0700),
    _city("atyrau", "Атырау", "Атырауская обл.", 47.0945, 51.9238),
    _city("oskemen", "Усть-Каменогорск", "ВКО", 49.9483, 82.6285),
    _city("taraz", "Тараз", "Жамбылская обл.", 42.9000, 71.3667),
    _city("taldykorgan", "Талдыкорган", "Жетысуская обл.", 45.0156, 78.3739),
    {
        "id": "kz-uralsk",
        "code": "uralsk",
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
    _city("karaganda", "Караганда", "Карагандинская обл.", 49.8047, 73.1094),
    _city("kostanay", "Костанай", "Костанайская обл.", 53.2144, 63.6246),
    _city("kyzylorda", "Кызылорда", "Кызылординская обл.", 44.8488, 65.4823),
    {
        "id": "kz-aktau",
        "code": "aktau",
        "name": "Актау",
        "oblast": "Мангистауская обл.",
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
    _city("pavlodar", "Павлодар", "Павлодарская обл.", 52.2871, 76.9674),
    _city("petropavl", "Петропавловск", "СКО", 54.8756, 69.1628),
    _city("turkistan", "Туркестан", "Туркестанская обл.", 43.2973, 68.2517),
    _city("zhezkazgan", "Жезказган", "Улытауская обл.", 47.7833, 67.7000),
    _city("semey", "Семей", "Абайская обл.", 50.4111, 80.2275),
]


def catalog_by_id(city_id: str) -> dict[str, Any] | None:
    return next((c for c in GEO_CATALOG_CITIES if c["id"] == city_id), None)


def catalog_city_summary(city: dict[str, Any]) -> dict[str, Any]:
    districts = city.get("districts") or []
    md_count = sum(len(d.get("microdistricts") or []) for d in districts)
    st_count = sum(len(d.get("streets") or []) for d in districts)
    return {
        "id": city["id"],
        "code": city.get("code"),
        "name": city["name"],
        "oblast": city.get("oblast"),
        "districts": len(districts),
        "microdistricts": md_count,
        "streets": st_count,
    }
