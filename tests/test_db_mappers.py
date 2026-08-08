"""Маппер ORM→DTO берёт публичный код из загруженной связи, без глобального словаря.

Регресс на находку P1: раньше коды владельца/улицы резолвились через модульные
словари _OWNER_UUID_TO_CODE/_STREET_UUID_TO_CODE, которые DbStore перезаписывал на
каждый запрос — гонка между параллельными запросами разных городов (в ответе мог
оказаться чужой код). Словари удалены; проверяем, что маппер опирается на связь.
"""
from __future__ import annotations

import uuid
from datetime import date
from types import SimpleNamespace

from app.enums import ObjectStatus
from db import mappers


def _row(*, owner_id, owner=None, street_id=None, street_row=None):
    ns = SimpleNamespace(
        id=uuid.uuid4(), code="o5", name="Кафе", type="Кафе", category="еда",
        address="ул. Абая 1", lat=51.2, lng=51.3, district_id=None, microdistrict_id="m1",
        street="Абая", street_id=street_id, house="1", apartment=None,
        owner_id=owner_id, status=ObjectStatus.not_inspected, responsible="",
        created_at=date(2026, 7, 1), updated_at=date(2026, 7, 1),
    )
    if owner is not None:
        ns.owner = owner
    if street_row is not None:
        ns.street_row = street_row
    return ns


def test_owner_code_from_loaded_relationship():
    owner_uid = uuid.uuid4()
    owner = SimpleNamespace(id=owner_uid, code="w11")
    dto = mappers.city_object(_row(owner_id=owner_uid, owner=owner))
    assert dto.ownerId == "w11"


def test_owner_falls_back_to_uuid_when_relationship_absent():
    owner_uid = uuid.uuid4()
    # связь не загружена и не догружается (нет .owner) → детерминированный UUID, не чужой код
    dto = mappers.city_object(_row(owner_id=owner_uid))
    assert dto.ownerId == str(owner_uid)


def test_no_owner_returns_placeholder():
    dto = mappers.city_object(_row(owner_id=None))
    assert dto.ownerId == "w4"


def test_street_code_from_loaded_relationship():
    street_uid = uuid.uuid4()
    street = SimpleNamespace(id=street_uid, code="s3")
    dto = mappers.city_object(_row(owner_id=None, street_id=street_uid, street_row=street))
    assert dto.streetId == "s3"


def test_global_code_maps_removed():
    # само существование удалено — гонки больше нет
    assert not hasattr(mappers, "_OWNER_UUID_TO_CODE")
    assert not hasattr(mappers, "set_owner_code_map")
