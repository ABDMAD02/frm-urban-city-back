"""Force-change: выданный temp-пароль обязан быть сменён при первом входе.

Контракт:
- login возвращает user.passwordChangeRequired=true для свежесозданного аккаунта;
- пока флаг стоит — операционные ручки и /auth/me отдают 403 password_change_required;
- /auth/change-password доступен (иначе тупик) и снимает флаг;
- после смены тот же access-токен проходит гейт.
"""
from __future__ import annotations

API = "/api/v1"


def _new_urbanist_creds(client, admin):
    r = client.post(f"{API}/users",
                    json={"name": "Форс Ченж", "role": "urbanist", "position": "инспектор"},
                    headers=admin)
    assert r.status_code == 201, r.text
    c = r.json()["credentials"]
    return c["login"], c["tempPassword"]


def test_new_account_must_change_password_then_unblocks(client, region_admin):
    login, temp_pw = _new_urbanist_creds(client, region_admin)

    # 1) вход по temp-паролю проходит, но помечен флагом
    r = client.post(f"{API}/auth/v2/login", json={"email": login, "password": temp_pw})
    assert r.status_code == 200, r.text
    assert r.json()["user"]["passwordChangeRequired"] is True
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}

    # 2) операционные ручки закрыты гейтом
    me = client.get(f"{API}/auth/me", headers=h)
    assert me.status_code == 403
    assert me.json()["code"] == "password_change_required"
    assert client.get(f"{API}/objects", headers=h).status_code == 403

    # 3) сменить пароль можно (no-gate), это снимает флаг
    ch = client.post(f"{API}/auth/change-password",
                     json={"oldPassword": temp_pw, "newPassword": "Str0ngPass!"}, headers=h)
    assert ch.status_code == 204, ch.text

    # 4) тот же токен теперь проходит; флаг снят
    me2 = client.get(f"{API}/auth/me", headers=h)
    assert me2.status_code == 200, me2.text
    assert me2.json()["passwordChangeRequired"] is False

    # 5) новый пароль валиден для входа, старый temp — уже нет
    assert client.post(f"{API}/auth/v2/login",
                       json={"email": login, "password": "Str0ngPass!"}).status_code == 200
    assert client.post(f"{API}/auth/v2/login",
                       json={"email": login, "password": temp_pw}).status_code == 401


def test_seed_users_not_gated(client, region_admin):
    """Сид-аккаунты (не temp) работают без смены пароля — флаг только у новых/сброшенных."""
    me = client.get(f"{API}/auth/me", headers=region_admin)
    assert me.status_code == 200, me.text
    assert me.json()["passwordChangeRequired"] is False
