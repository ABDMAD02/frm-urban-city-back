"""RBAC на мутациях: контролируемая сторона (owner) не действует как контролёр.

Регресс-тесты на находку C4 из аудита: до фикса владелец мог создать объект,
провести проверку своего объекта и закрыть/продлить собственное уведомление.
"""
from __future__ import annotations

API = "/api/v1"


def test_owner_cannot_create_object(client, owner):
    r = client.post(
        f"{API}/objects",
        json={"name": "Левый объект", "type": "Кафе", "lat": 51.2, "lng": 51.3, "ownerId": "w2"},
        headers=owner,
    )
    assert r.status_code == 403, r.text
    assert r.json()["code"] == "forbidden_role"


def test_owner_cannot_inspect_own_object(client, owner):
    body = {
        "inspection": {
            "id": "", "objectId": "o5", "inspector": "self", "date": "2026-08-08",
            "result": "compliant", "checklist": [], "comment": "", "photoIds": [],
        },
        "status": "compliant",
        "photos": [{"id": "", "objectId": "o5", "kind": "after", "caption": "",
                    "date": "2026-08-08", "author": "self"}],
    }
    r = client.post(f"{API}/objects/o5/inspections", json=body, headers=owner)
    assert r.status_code == 403, r.text


def test_owner_cannot_close_own_prescription(client, owner):
    # pr1 — просроченное уведомление по объекту владельца (o5).
    r = client.patch(
        f"{API}/prescriptions/pr1",
        json={"status": "closed", "deadline": "2035-01-01"},
        headers=owner,
    )
    assert r.status_code == 403, r.text


def test_owner_cannot_reinspect(client, owner):
    r = client.post(f"{API}/objects/o5/reinspections", json={"result": "fixed"}, headers=owner)
    assert r.status_code == 403, r.text


# --- Легитимные роли по-прежнему работают (не сломали контракт) ---

def test_urbanist_can_create_object(client, urbanist):
    r = client.post(
        f"{API}/objects",
        json={"name": "Ларёк", "type": "Киоск", "lat": 51.22, "lng": 51.37,
              "microdistrictId": "m1", "ownerId": "w2"},
        headers=urbanist,
    )
    assert r.status_code == 201, r.text


def test_region_admin_can_patch_prescription(client, region_admin):
    r = client.patch(f"{API}/prescriptions/pr1", json={"deadline": "2026-12-31"}, headers=region_admin)
    assert r.status_code == 200, r.text
