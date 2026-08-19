"""Обратный геокодер (координаты → адрес). Провайдер за флагом GEOCODER_PROVIDER.

MVP-реализация: ``nominatim`` (OpenStreetMap). Кэш — в процессе, по округлённым
до 5 знаков координатам (TTL 30 суток); при масштабировании выносится в таблицу
без смены контракта. Соблюдаем требования Nominatim: User-Agent и ≤1 запрос/сек.

Идентификаторы справочников (streetId/microdistrictId/districtId) здесь НЕ
заполняются — только текстовый адрес/улица/дом; сопоставление с гео-справочником
города (при уверенном совпадении) делает вызывающий слой.
"""
from __future__ import annotations

import logging
import threading
import time

import httpx

from app import config

logger = logging.getLogger(__name__)

_NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
_USER_AGENT = "UrbanCity/1.0 (govtech.kz; reverse-geocode)"
_CACHE_TTL_SECONDS = 30 * 24 * 3600
_MIN_INTERVAL = 1.0  # ≤1 req/sec — требование Nominatim

_cache: dict[tuple[float, float], tuple[float, dict]] = {}
_lock = threading.Lock()
_last_call = [0.0]


class GeocoderUnavailable(Exception):
    """Геокодер выключен, не настроен или источник не ответил → маршрут отдаёт 503."""


def _key(lat: float, lng: float) -> tuple[float, float]:
    return (round(lat, 5), round(lng, 5))


def reverse(lat: float, lng: float) -> dict:
    """Координаты → словарь адреса. Бросает GeocoderUnavailable при недоступности."""
    provider = config.GEOCODER_PROVIDER
    if provider != "nominatim":
        # off / 2gis (не реализован) — честный отказ, без выдумки адреса.
        raise GeocoderUnavailable(provider or "off")

    key = _key(lat, lng)
    now = time.time()
    with _lock:
        cached = _cache.get(key)
        if cached and now - cached[0] < _CACHE_TTL_SECONDS:
            return cached[1]

    with _lock:
        wait = _MIN_INTERVAL - (time.time() - _last_call[0])
        if wait > 0:
            time.sleep(wait)
        _last_call[0] = time.time()

    try:
        resp = httpx.get(
            _NOMINATIM_URL,
            params={"lat": lat, "lon": lng, "format": "jsonv2", "addressdetails": 1},
            headers={"User-Agent": _USER_AGENT, "Accept-Language": "ru"},
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # сеть/таймаут/HTTP-ошибка — недоступность источника
        logger.warning("nominatim reverse failed: %s: %s", type(exc).__name__, exc)
        raise GeocoderUnavailable("provider_error") from exc

    addr = data.get("address", {}) or {}
    street = addr.get("road") or addr.get("pedestrian") or addr.get("residential") or ""
    house = addr.get("house_number") or ""
    result = {
        "address": data.get("display_name") or "",
        "street": street,
        "house": house,
        "streetId": None,
        "microdistrictId": None,
        "districtId": None,
        "confidence": "high" if street else "low",
    }
    with _lock:
        _cache[key] = (now, result)
    return result
