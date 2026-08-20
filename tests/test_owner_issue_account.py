"""Создание аккаунта-владельца существующему бизнесу — POST /owners/{id}/account."""
from __future__ import annotations

API = "/api/v1"


def _business_without_account(client, region_admin):
    # Батч-импорт заводит бизнес record-only (без аккаунта-владельца).
    r = client.post(f"{API}/owners/import",
                    json={"items": [{"name": "ТОО Без Аккаунта", "legalForm": "ТОО", "bin": "180940055667"}]},
                    headers=region_admin)
    assert r.status_code == 200, r.text
    return r.json()["createdOwnerIds"][0]


def test_issue_account_creates_and_links(client, region_admin):
    wid = _business_without_account(client, region_admin)
    r = client.post(f"{API}/owners/{wid}/account", headers=region_admin)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["owner"]["ownerUserId"]                       # привязан аккаунт
    creds = body["credentials"]
    assert creds and creds["login"] and creds["tempPassword"]  # выданы креды
    # логин работает
    ok = client.post(f"{API}/auth/v2/login", json={"email": creds["login"], "password": creds["tempPassword"]})
    assert ok.status_code == 200, ok.text
    assert ok.json()["user"]["role"] == "owner"


def test_issue_account_twice_409(client, region_admin):
    wid = _business_without_account(client, region_admin)
    assert client.post(f"{API}/owners/{wid}/account", headers=region_admin).status_code == 201
    r = client.post(f"{API}/owners/{wid}/account", headers=region_admin)
    assert r.status_code == 409, r.text
    j = r.json()
    assert (j.get("code") or j.get("detail", {}).get("code")) == "already_has_account"


def test_issue_account_requires_admin(client, urbanist, region_admin):
    wid = _business_without_account(client, region_admin)
    r = client.post(f"{API}/owners/{wid}/account", headers=urbanist)
    assert r.status_code == 403, r.text
