"""Авто-создание логина владельца при заведении бизнеса (ТЗ-02/04)."""
from __future__ import annotations

API = "/api/v1"


def test_create_owner_autocreates_login(client, region_admin):
    r = client.post(f"{API}/owners",
                    json={"name": "ТОО Поле", "legalForm": "ТОО", "phone": "+77010000000", "bin": "180540027777"},
                    headers=region_admin)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["owner"]["name"] == "ТОО Поле"
    creds = body["credentials"]
    assert creds and creds["login"] and creds["tempPassword"]
    # логин владельца работает
    ok = client.post(f"{API}/auth/v2/login", json={"email": creds["login"], "password": creds["tempPassword"]})
    assert ok.status_code == 200, ok.text
    me = client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {ok.json()['access_token']}"}).json()
    assert me["role"] == "owner"
    # созданный аккаунт связан с бизнесом
    assert body["owner"]["ownerUserId"] == me["id"]


def test_create_owner_with_existing_account_no_creds(client, region_admin):
    # завести бизнес на существующий аккаунт-владельца (u2) — без нового логина
    r = client.post(f"{API}/owners",
                    json={"name": "ТОО На аккаунт", "legalForm": "ТОО", "phone": "+77010000001", "ownerUserId": "u2"},
                    headers=region_admin)
    assert r.status_code == 201, r.text
    assert r.json()["credentials"] is None
    assert r.json()["owner"]["ownerUserId"] == "u2"


def test_urbanist_creates_business_with_login(client, urbanist):
    # полевой сценарий: урбанист заводит бизнес → сразу есть логин владельца
    r = client.post(f"{API}/owners",
                    json={"name": "ИП Ларёк", "legalForm": "ИП", "phone": "+77010000002"},
                    headers=urbanist)
    assert r.status_code == 201, r.text
    assert r.json()["credentials"]["login"]
