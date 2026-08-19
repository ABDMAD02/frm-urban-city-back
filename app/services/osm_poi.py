"""Выгрузка POI из OpenStreetMap (Overpass API) для сева объектов города.

Тянет точки shop=*/amenity=<категории> в радиусе вокруг центра города,
маппит OSM-теги → :class:`~app.models.ObjectImportItem` (name/type/lat/lng/
address). Дедуп и создание — на слое стора (import_objects).

Лицензия данных — ODbL: при показе/использовании обязательна атрибуция
«© OpenStreetMap contributors».
"""
from __future__ import annotations

import logging

import httpx

from app import config
from app.models import ObjectImportItem

logger = logging.getLogger(__name__)


class OverpassUnavailable(Exception):
    """Overpass не ответил/таймаут/ошибка — маршрут отдаёт 503."""


# Категории amenity, которые считаем «объектами города» (бизнес-POI).
_AMENITIES = [
    "cafe", "restaurant", "fast_food", "bar", "pub", "pharmacy", "bank",
    "fuel", "clinic", "hospital", "dentist", "cinema", "marketplace", "fitness_centre",
]

# OSM-тег → человекочитаемый тип объекта (ru). Fallback — сам тег.
_TYPE_RU = {
    "cafe": "Кафе", "restaurant": "Ресторан", "fast_food": "Фастфуд", "bar": "Бар",
    "pub": "Паб", "pharmacy": "Аптека", "bank": "Банк", "fuel": "АЗС",
    "clinic": "Клиника", "hospital": "Больница", "dentist": "Стоматология",
    "cinema": "Кинотеатр", "marketplace": "Рынок", "fitness_centre": "Фитнес",
    "shop": "Магазин",
}


def _build_query(lat: float, lng: float, radius_m: int) -> str:
    amen = "|".join(_AMENITIES)
    around = f"(around:{radius_m},{lat},{lng})"
    return (
        f"[out:json][timeout:{config.OVERPASS_TIMEOUT}];"
        "("
        f'node["shop"]{around};'
        f'way["shop"]{around};'
        f'node["amenity"~"{amen}"]{around};'
        f'way["amenity"~"{amen}"]{around};'
        ");"
        "out center tags;"
    )


def _type_of(tags: dict) -> str:
    if tags.get("shop"):
        return _TYPE_RU["shop"]
    amen = tags.get("amenity")
    return _TYPE_RU.get(amen, amen or "Объект")


def _address_of(tags: dict) -> str | None:
    street = tags.get("addr:street")
    house = tags.get("addr:housenumber")
    if street and house:
        return f"{street}, {house}"
    return street or None


def fetch_pois(lat: float, lng: float, radius_m: int) -> list[ObjectImportItem]:
    """Точки бизнес-POI вокруг центра города → items для импорта."""
    query = _build_query(lat, lng, radius_m)
    try:
        resp = httpx.post(
            config.OVERPASS_URL,
            data={"data": query},
            headers={"User-Agent": "UrbanCity/1.0 (govtech.kz; poi-seed)"},
            timeout=config.OVERPASS_TIMEOUT + 10,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # сеть/таймаут/HTTP/JSON
        logger.warning("overpass fetch failed: %s: %s", type(exc).__name__, exc)
        raise OverpassUnavailable(str(exc)) from exc

    items: list[ObjectImportItem] = []
    for el in data.get("elements", []):
        tags = el.get("tags", {}) or {}
        name = (tags.get("name") or "").strip()
        if not name:
            continue  # безымянные POI не сеем
        # node → lat/lon; way → center.
        plat = el.get("lat") if el.get("lat") is not None else (el.get("center") or {}).get("lat")
        plng = el.get("lon") if el.get("lon") is not None else (el.get("center") or {}).get("lon")
        if plat is None or plng is None:
            continue
        items.append(ObjectImportItem(
            name=name,
            type=_type_of(tags),
            lat=float(plat),
            lng=float(plng),
            address=_address_of(tags),
        ))
    return items
