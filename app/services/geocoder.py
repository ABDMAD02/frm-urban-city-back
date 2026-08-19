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
import re
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
    # Кандидат на микрорайон из разных полей Nominatim (по стране/зуму отличаются).
    microdistrict = (
        addr.get("quarter") or addr.get("neighbourhood") or addr.get("suburb")
        or addr.get("city_district") or ""
    )
    result = {
        "address": data.get("display_name") or "",
        "street": street,
        "house": house,
        "microdistrict": microdistrict,   # только для сопоставления с справочником, не в DTO
        "streetId": None,
        "microdistrictId": None,
        "districtId": None,
        "confidence": "high" if street else "low",
    }
    with _lock:
        _cache[key] = (now, result)
    return result


# Слова-типы (ru/kk), которые убираем перед сравнением имён улиц/мкр.
_TYPE_WORDS = {
    "улица", "ул", "проспект", "пр", "прт", "переулок", "пер", "бульвар", "б",
    "шоссе", "проезд", "тупик", "площадь", "пл", "микрорайон", "мкр", "мкрн",
    "район", "жилой", "массив", "квартал",
    "көше", "көшесі", "даңғыл", "даңғылы", "шағын", "ауданы", "ауданшасы", "алаңы",
}


def _norm(name: str | None) -> str:
    """Нормализация имени для сравнения: нижний регистр, без пунктуации и слов-типов."""
    s = (name or "").lower().replace("ё", "е")
    s = re.sub(r"[^\w\s]", " ", s, flags=re.UNICODE)
    tokens = [t for t in s.split() if t and t not in _TYPE_WORDS]
    return " ".join(tokens).strip()


def match_ids(street_name, md_name, streets, microdistricts):
    """Имя улицы/микрорайона из геокодера → id из справочника города.

    Возвращает (streetId, microdistrictId, districtId); None там, где нет
    уверенного совпадения по нормализованному имени (§B-BE-2 ТЗ).
    """
    st_id = md_id = d_id = None
    ns = _norm(street_name)
    if ns:
        for s in streets:
            if _norm(s.name) == ns:
                st_id = s.id
                d_id = d_id or getattr(s, "districtId", None)
                if getattr(s, "microdistrictId", None):
                    md_id = s.microdistrictId
                break
    if md_id is None:
        nm = _norm(md_name)
        if nm:
            for m in microdistricts:
                if _norm(m.name) == nm:
                    md_id = m.id
                    d_id = d_id or getattr(m, "districtId", None)
                    break
    return st_id, md_id, d_id
