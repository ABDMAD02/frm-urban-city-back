"""Идентичность региона: непрозрачный стабильный id + изменяемый слаг code."""
from __future__ import annotations

from tests.conftest import API


def _provision(client, superadmin, code="opaqcity", name="Опак Сити"):
    body = {"code": code, "name": name, "adminName": "Тест Админ"}
    r = client.post(f"{API}/platform/regions", headers=superadmin, json=body)
    assert r.status_code == 201, r.text
    return r.json()["region"]


def test_provision_id_is_opaque_and_differs_from_code(client, superadmin):
    region = _provision(client, superadmin)
    assert region["code"] == "opaqcity"
    assert region["id"] != region["code"]      # id не равен слагу
    assert region["id"].startswith("reg-")     # непрозрачный стабильный ключ


def test_provision_from_catalog_id_opaque(client, superadmin):
    body = {"code": "aktaucity", "name": "Актау", "adminName": "Т",
            "geo": {"source": "catalog", "cityCatalogId": "kz-aktau"}}
    r = client.post(f"{API}/platform/regions", headers=superadmin, json=body)
    assert r.status_code == 201, r.text
    region = r.json()["region"]
    assert region["code"] == "aktaucity" and region["id"] != "aktaucity"


def test_rename_code_keeps_id_and_data(client, superadmin):
    # Провижн из каталога → есть гео, привязанная к id региона; code с опечаткой.
    body = {"code": "aktauu", "name": "Актау", "adminName": "Т",
            "geo": {"source": "catalog", "cityCatalogId": "kz-aktau"}}
    region = client.post(f"{API}/platform/regions", headers=superadmin, json=body).json()["region"]
    rid = region["id"]

    # Опечатку в code правим переименованием — id остаётся прежним.
    r = client.patch(f"{API}/platform/regions/{rid}", headers=superadmin, json={"code": "aktau"})
    assert r.status_code == 200, r.text
    assert r.json()["id"] == rid and r.json()["code"] == "aktau"

    # Регион и его данные по-прежнему доступны по стабильному id.
    assert client.get(f"{API}/platform/regions/{rid}", headers=superadmin).json()["code"] == "aktau"
    d = client.get(f"{API}/platform/regions/{rid}/districts", headers=superadmin)
    assert d.status_code == 200


def test_rename_to_taken_code_409(client, superadmin):
    region = _provision(client, superadmin, code="uniqcity", name="Уник")
    rid = region["id"]
    # uralsk засеян в сторе — занять его код нельзя.
    r = client.patch(f"{API}/platform/regions/{rid}", headers=superadmin, json={"code": "uralsk"})
    assert r.status_code == 409
    assert r.json()["code"] == "region_exists"


def test_rename_name_only(client, superadmin):
    region = _provision(client, superadmin, code="renamecity", name="Старое")
    rid = region["id"]
    r = client.patch(f"{API}/platform/regions/{rid}", headers=superadmin, json={"name": "Новое"})
    assert r.status_code == 200 and r.json()["name"] == "Новое" and r.json()["code"] == "renamecity"
