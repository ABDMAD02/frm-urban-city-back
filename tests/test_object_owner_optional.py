# -*- coding: utf-8 -*-
"""Владелец у объекта необязателен (регрессия на хардкод демо-владельца w4).

Дефект, найденный на проде 20.08.2026: массовый импорт объектов из OSM падал
на каждой строке с ``422 invalid_owner_region``. Причина — в ``DbStore`` пустой
``ownerId`` подменялся захардкоженным ``w4`` (владелец демо-региона Уральска),
после чего проверка региона отклоняла запись. В памяти проверки нет, поэтому
тесты на memory-сторе дефект не ловили, а PostgreSQL валился.

Колонка ``city_object.owner_id`` nullable, а ``ownerId`` не входит в required
у ``CreateObjectRequest`` — объект без владельца является нормой (сев из OSM,
постановка на учёт «в поле», когда собственник ещё не установлен).
"""
from db.repository import DbStore


def _bare_store() -> DbStore:
    """Экземпляр без сессии: для пустого ownerId обращение к БД не требуется."""
    return DbStore.__new__(DbStore)


def test_empty_owner_resolves_to_none():
    """Низкий уровень: пустой ownerId не подставляет чужого владельца."""
    store = _bare_store()
    assert store._resolve_owner_uuid(None, region_id="atyrau") is None
    assert store._resolve_owner_uuid("", region_id="atyrau") is None
    assert store._resolve_owner_uuid("   ", region_id="atyrau") is None


def test_no_hardcoded_demo_owner_left():
    """Ни один путь создания объекта не подставляет чужого владельца по умолчанию."""
    import inspect

    src = inspect.getsource(DbStore._resolve_owner_uuid)
    assert '"w4"' not in src and "'w4'" not in src


def test_object_without_owner_created_in_memory(client, region_admin):
    """Сквозная проверка на memory-сторе: объект без ownerId создаётся."""
    r = client.post(
        "/api/v1/objects",
        json={"name": "Киоск без собственника", "type": "Магазин", "lat": 47.11, "lng": 51.88},
        headers=region_admin,
    )
    assert r.status_code in (200, 201), r.text
    owner_id = r.json().get("ownerId")
    assert owner_id, "объект должен получить владельца"
    assert owner_id != "w4", "объект не должен приписываться демо-владельцу Уральска"

    owners = client.get("/api/v1/owners", headers=region_admin).json()
    placeholder = next((o for o in owners if o["id"] == owner_id), None)
    assert placeholder and placeholder["name"] == "Собственник не установлен", placeholder


def test_owner_matched_by_name_from_seeded_registry(client, region_admin):
    """Сев объектов подбирает владельца среди уже засеянных бизнесов по названию.

    Реестр юрлиц засевается отдельно (egov gbd_ul), у точек OSM БИН нет — связь
    строится по названию: «Береке» ↔ «ТОО «Береке»». Сравнение без регистра,
    кавычек и организационной формы.
    """
    from db.repository import _owner_key

    assert _owner_key("Береке") == _owner_key('ТОО «Береке»')
    assert _owner_key("ИП Нурланова") != _owner_key("ТОО Береке")
    # Пустое и мусорное имя ключа не дают — владелец не подставится наугад.
    assert _owner_key("") == ""
    assert _owner_key("ТОО") == ""
