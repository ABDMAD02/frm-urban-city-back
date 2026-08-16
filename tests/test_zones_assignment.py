"""Зоны урбаниста + переопределение ответственного (ТЗ §3.1, тест-кейсы TC-1..TC-9).

Проверяет нормативное правило скоупа: override > зона; чужой override скрывает объект;
урбанист без зон → пустой скоуп; нераспределённые видны админу.
"""
from __future__ import annotations

API = "/api/v1"


def _new_urbanist(client, admin, name):
    r = client.post(f"{API}/users", json={"name": name, "role": "urbanist", "position": "инспектор"}, headers=admin)
    assert r.status_code == 201, r.text
    return r.json()["user"]["id"]


def _new_urbanist_with_creds(client, admin, name):
    r = client.post(f"{API}/users", json={"name": name, "role": "urbanist", "position": "инспектор"}, headers=admin)
    assert r.status_code == 201, r.text
    c = r.json()["credentials"]
    return r.json()["user"]["id"], c["login"], c["tempPassword"]


def _login(client, email, pw):
    return {"Authorization": f"Bearer {client.post(f'{API}/auth/v2/login', json={'email': email, 'password': pw}).json()['access_token']}"}


def _first_login(client, login, temp_pw, new_pw="ZonesPass123!"):
    """Первый вход по temp-паролю: сервер требует force-change. Меняем пароль и
    возвращаем рабочие headers (тот же токен после смены проходит гейт)."""
    r = client.post(f"{API}/auth/v2/login", json={"email": login, "password": temp_pw})
    assert r.status_code == 200, r.text
    assert r.json()["user"]["passwordChangeRequired"] is True
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    ch = client.post(f"{API}/auth/change-password",
                     json={"oldPassword": temp_pw, "newPassword": new_pw}, headers=h)
    assert ch.status_code == 204, ch.text
    return h


def _obj_ids(client, headers):
    return {o["id"] for o in client.get(f"{API}/objects", headers=headers).json()}


def _make_object(client, headers, md="m1", street_id=None):
    body = {"name": "Тест-объект", "type": "Кафе", "lat": 51.2, "lng": 51.3,
            "microdistrictId": md, "streetId": street_id, "ownerId": "w2"}
    r = client.post(f"{API}/objects", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


# u1 — урбанист (пароль UC-0001-u1), a.kenzhebekov — админ (UC-0003-u3)

def test_tc1_override_beats_zone(client, region_admin, urbanist):
    # u1 зона = m1; объект в m1
    client.patch(f"{API}/users/u1", json={"microdistrictIds": ["m1"], "streetIds": []}, headers=region_admin)
    oid = _make_object(client, region_admin, md="m1")
    u1 = _login(client, "a.nurlanova@uralsk.kz", "UC-0001-u1")
    assert oid in _obj_ids(client, u1)                      # видит по зоне
    # админ отдаёт объект другому урбанисту V
    v_id = _new_urbanist(client, region_admin, "Вторая Урбанистка")
    r = client.patch(f"{API}/objects/{oid}", json={"patch": {"assignedUrbanistId": v_id}}, headers=region_admin)
    assert r.status_code == 200, r.text
    assert r.json()["assignedUrbanistId"] == v_id
    assert oid not in _obj_ids(client, u1)                  # override перекрыл зону


def test_tc5_urbanist_without_zones_sees_empty(client, region_admin):
    _v_id, login, pw = _new_urbanist_with_creds(client, region_admin, "Без Зон")
    vh = _first_login(client, login, pw)                    # temp-пароль → force-change → рабочая сессия
    assert _obj_ids(client, vh) == set()                    # пустой скоуп, не весь регион


def test_tc6_clear_override_returns_to_zone(client, region_admin, urbanist):
    client.patch(f"{API}/users/u1", json={"microdistrictIds": ["m1"]}, headers=region_admin)
    oid = _make_object(client, region_admin, md="m1")
    v_id = _new_urbanist(client, region_admin, "Врем Овнер")
    client.patch(f"{API}/objects/{oid}", json={"patch": {"assignedUrbanistId": v_id}}, headers=region_admin)
    u1 = _login(client, "a.nurlanova@uralsk.kz", "UC-0001-u1")
    assert oid not in _obj_ids(client, u1)
    # снять override (null) → вернуть в зону
    client.patch(f"{API}/objects/{oid}", json={"patch": {"assignedUrbanistId": None}}, headers=region_admin)
    assert oid in _obj_ids(client, u1)


def test_tc2_unassigned_visible_to_admin_only(client, region_admin, urbanist):
    # объект в мкр, которого нет ни в чьей зоне
    client.patch(f"{API}/users/u1", json={"microdistrictIds": ["m1"]}, headers=region_admin)
    oid = _make_object(client, region_admin, md="m2")     # m2 не в зоне u1
    u1 = _login(client, "a.nurlanova@uralsk.kz", "UC-0001-u1")
    assert oid not in _obj_ids(client, u1)                 # урбанист не видит
    unassigned = {o["id"] for o in client.get(f"{API}/objects/unassigned", headers=region_admin).json()}
    assert oid in unassigned                                # админ видит в нераспределённых


def test_tc8_validation(client, region_admin, owner):
    oid = _make_object(client, region_admin, md="m1")
    # назначить не-урбаниста (владельца) → 409 invalid_role
    r = client.patch(f"{API}/objects/{oid}", json={"patch": {"assignedUrbanistId": "u2"}}, headers=region_admin)
    assert r.status_code == 409 and r.json()["code"] == "invalid_role", r.text
    # не-админ (владелец) пытается назначить → 403
    r2 = client.patch(f"{API}/objects/{oid}", json={"patch": {"assignedUrbanistId": "u1"}}, headers=owner)
    assert r2.status_code == 403, r2.text


def test_tc9_bulk_assign_idempotent(client, region_admin):
    o1 = _make_object(client, region_admin, md="m1")
    o2 = _make_object(client, region_admin, md="m1")
    r = client.post(f"{API}/objects/bulk-assign",
                    json={"ids": [o1, o2, o2, "нет-такого"], "assignedUrbanistId": "u1"},
                    headers=region_admin)
    assert r.status_code == 200, r.text
    assert r.json()["assigned"] == 2


def test_coverage_summary(client, region_admin, urbanist):
    client.patch(f"{API}/users/u1", json={"microdistrictIds": ["m1"]}, headers=region_admin)
    _make_object(client, region_admin, md="m1")   # в зоне u1
    _make_object(client, region_admin, md="m2")   # нераспределённый
    cov = client.get(f"{API}/coverage/summary", headers=region_admin).json()
    u1_row = next(r for r in cov["urbanists"] if r["urbanistId"] == "u1")
    assert u1_row["objects"] >= 1
    assert cov["unassigned"] >= 1


def test_reset_password_keeps_enum_status(client, region_admin):
    # регресс: memory update_user ставил status строкой "active" → ломал .value
    uid, login, _pw = _new_urbanist_with_creds(client, region_admin, "Сброс Пароля")
    reset = client.patch(f"{API}/users/{uid}", json={"resetPassword": True}, headers=region_admin)
    assert reset.status_code == 200, reset.text
    new_pw = reset.json()["credentials"]["tempPassword"]
    # вход по новому паролю не должен падать 500 (status теперь enum)
    r = client.post(f"{API}/auth/v2/login", json={"email": login, "password": new_pw})
    assert r.status_code == 200, r.text
    # после сброса — снова force-change; /auth/me закрыт гейтом, пока не сменим пароль
    assert r.json()["user"]["passwordChangeRequired"] is True
    tok = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert client.get(f"{API}/auth/me", headers=tok).status_code == 403
    ch = client.post(f"{API}/auth/change-password",
                     json={"oldPassword": new_pw, "newPassword": "ResetPass123!"}, headers=tok)
    assert ch.status_code == 204, ch.text
    me = client.get(f"{API}/auth/me", headers=tok)
    assert me.status_code == 200, me.text
