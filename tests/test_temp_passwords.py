"""Временные пароли новых учёток непредсказуемы (находка C2).

Раньше пароль вычислялся из последовательного кода пользователя
(u2 → UC-0002-u2), логин выводился из ФИО — перебор < 1000 запросов.
Операционное создание/сброс теперь используют random_temp_password().
"""
from __future__ import annotations

from app.user_helpers import temp_password

API = "/api/v1"


def test_created_user_password_is_not_derivable(client, region_admin):
    r = client.post(
        f"{API}/users",
        json={"name": "Ержан Абдуллин", "role": "urbanist", "position": "спец"},
        headers=region_admin,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    uid = body["user"]["id"]
    issued = body["credentials"]["tempPassword"]
    login = body["credentials"]["login"]

    # Пароль по возвращённым кредам работает.
    ok = client.post(f"{API}/auth/v2/login", json={"email": login, "password": issued})
    assert ok.status_code == 200, ok.text

    # Старая предсказуемая догадка (из кода/id) — НЕ работает.
    guess = temp_password(uid)
    assert guess != issued
    bad = client.post(f"{API}/auth/v2/login", json={"email": login, "password": guess})
    assert bad.status_code == 401, "предсказуемый пароль не должен подходить"


def test_two_users_get_distinct_passwords(client, region_admin):
    pwds = set()
    for name in ("Асхат Болатов", "Гульмира Сериковна"):
        r = client.post(
            f"{API}/users",
            json={"name": name, "role": "urbanist", "position": "спец"},
            headers=region_admin,
        )
        assert r.status_code == 201, r.text
        pwds.add(r.json()["credentials"]["tempPassword"])
    assert len(pwds) == 2, "пароли разных юзеров не должны совпадать"


def test_provisioned_admin_password_is_random(client, superadmin):
    r = client.post(
        f"{API}/platform/regions",
        json={"code": "testcity", "name": "Тестгород", "adminName": "Админ Тестов"},
        headers=superadmin,
    )
    assert r.status_code == 201, r.text
    creds = r.json()["credentials"]
    ok = client.post(f"{API}/auth/v2/login", json={"email": creds["login"], "password": creds["tempPassword"]})
    assert ok.status_code == 200, ok.text
