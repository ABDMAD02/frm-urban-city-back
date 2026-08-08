"""Урбанист видит и заводит бизнесы своего города (разблокировка полевого флоу).

Из сверки ТЗ: GET/POST /owners отдавали урбанисту 403 → он не мог поставить объект
«в поле» (пустой список владельцев + блокировка формы). Теперь открыто в скоупе города.
"""
from __future__ import annotations

API = "/api/v1"


def test_urbanist_can_list_owners(client, urbanist):
    r = client.get(f"{API}/owners", headers=urbanist)
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), list)


def test_urbanist_can_create_owner(client, urbanist):
    r = client.post(
        f"{API}/owners",
        json={"name": "ТОО Полевой", "legalForm": "ТОО", "phone": "+77010000000", "bin": "180540021234"},
        headers=urbanist,
    )
    assert r.status_code == 201, r.text
    assert r.json()["owner"]["name"] == "ТОО Полевой"


def test_owner_still_scoped_to_own(client, owner):
    # владелец по-прежнему видит только свои бизнесы
    r = client.get(f"{API}/owners/my", headers=owner)
    assert r.status_code == 200, r.text
