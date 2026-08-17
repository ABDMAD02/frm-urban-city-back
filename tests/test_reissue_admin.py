"""Перевыпуск админа региона = СБРОС пароля существующему аккаунту in-place.

Регресс: раньше `POST /platform/regions/{id}/admin-account` блокировал старый
аккаунт и создавал новый — плодило логины (a.ildar → a.ildar2 → …) и падало
422 duplicate на повторном перевыпуске. Теперь тот же аккаунт (id/логин),
новый temp-пароль + force-change, повтор не ломается.
"""
from __future__ import annotations

from tests.conftest import API


def _region_admins(client, superadmin, region_id):
    r = client.get(f"{API}/platform/region-admin-accounts", headers=superadmin)
    assert r.status_code == 200, r.text
    return [a for a in r.json() if a["regionId"] == region_id]


def _reissue(client, superadmin, region_id, name="Акатов Ильдар Саинович"):
    r = client.post(
        f"{API}/platform/regions/{region_id}/admin-account",
        headers=superadmin,
        json={"name": name},
    )
    assert r.status_code == 201, r.text
    return r.json()["credentials"]


def test_reissue_resets_password_in_place(client, superadmin):
    # Провижн из каталога → регион сразу active, админ может логиниться.
    body = {
        "code": "reissuecity",
        "name": "Ре-issue Сити",
        "adminName": "Акатов Ильдар Саинович",
        "geo": {"source": "catalog", "cityCatalogId": "kz-uralsk"},
    }
    r = client.post(f"{API}/platform/regions", headers=superadmin, json=body)
    assert r.status_code == 201, r.text
    prov = r.json()
    region_id = prov["region"]["id"]
    login0 = prov["credentials"]["login"]
    pw0 = prov["credentials"]["tempPassword"]

    admins = _region_admins(client, superadmin, region_id)
    assert len(admins) == 1
    acc_id = admins[0]["id"]

    # исходный temp-пароль работает + force-change при первом входе
    r = client.post(f"{API}/auth/v2/login", json={"email": login0, "password": pw0})
    assert r.status_code == 200, r.text
    assert r.json()["user"]["passwordChangeRequired"] is True

    # ── Перевыпуск #1 ──
    creds1 = _reissue(client, superadmin, region_id)
    assert creds1["login"] == login0           # тот же логин, не a.ildar2
    assert creds1["tempPassword"] != pw0        # новый пароль

    admins = _region_admins(client, superadmin, region_id)
    assert len(admins) == 1                      # НЕ появилось нового/заблокированного
    assert admins[0]["id"] == acc_id             # тот же аккаунт
    assert admins[0]["status"] == "active"

    # старый пароль мёртв, новый работает + force-change
    assert (
        client.post(f"{API}/auth/v2/login", json={"email": login0, "password": pw0}).status_code
        == 401
    )
    r = client.post(f"{API}/auth/v2/login", json={"email": login0, "password": creds1["tempPassword"]})
    assert r.status_code == 200, r.text
    assert r.json()["user"]["passwordChangeRequired"] is True

    # ── Перевыпуск #2: НЕ должно быть 422 duplicate, логин/аккаунт прежние ──
    creds2 = _reissue(client, superadmin, region_id)
    assert creds2["login"] == login0
    assert creds2["tempPassword"] not in (pw0, creds1["tempPassword"])

    admins = _region_admins(client, superadmin, region_id)
    assert len(admins) == 1
    assert admins[0]["id"] == acc_id
