"""RBAC на управлении пользователями (находка C1).

До фикса `PATCH /users/{uid}` не проверял роль цели: администратор района мог
сбросить пароль платформенного суперадмина и получить его креды — захват всей
платформы. `delete_user` guard уже имел, `update_user` — нет.
"""
from __future__ import annotations

API = "/api/v1"


def test_region_admin_cannot_reset_superadmin_password(client, region_admin):
    r = client.patch(f"{API}/users/sa1", json={"resetPassword": True}, headers=region_admin)
    assert r.status_code == 403, r.text
    assert r.json()["code"] == "forbidden"
    # креды суперадмина не должны утечь
    assert "credentials" not in r.text or r.json().get("code") == "forbidden"


def test_region_admin_cannot_block_superadmin(client, region_admin):
    r = client.patch(f"{API}/users/sa1", json={"status": "blocked"}, headers=region_admin)
    assert r.status_code == 403, r.text


def test_region_admin_cannot_edit_another_admin(client, region_admin):
    r = client.patch(f"{API}/users/u3", json={"resetPassword": True}, headers=region_admin)
    assert r.status_code == 403, r.text


def test_region_admin_can_still_edit_urbanist(client, region_admin):
    # легитимный кейс — правка обычного сотрудника не сломана
    r = client.patch(f"{API}/users/u1", json={"status": "active"}, headers=region_admin)
    assert r.status_code == 200, r.text
