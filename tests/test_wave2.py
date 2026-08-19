"""Волна 2: ИИН/телефон у аккаунта (A-BE-1) и единый поиск (A-BE-2)."""
from __future__ import annotations

API = "/api/v1"


# ── A-BE-1: ИИН у аккаунта, уникален в городе ───────────────────────────
def test_user_iin_persisted_and_returned(client, region_admin):
    r = client.post(
        f"{API}/users",
        json={"name": "Асель Нурлан", "role": "urbanist", "position": "Специалист", "iin": "900101300111", "phone": "+77010001111"},
        headers=region_admin,
    )
    assert r.status_code == 201, r.text
    u = r.json()["user"]
    assert u["iin"] == "900101300111"
    assert u["phone"] == "+77010001111"


def test_user_iin_duplicate_in_city_409(client, region_admin):
    body = {"name": "Первый Человек", "role": "urbanist", "position": "Спец", "iin": "900202300222"}
    assert client.post(f"{API}/users", json=body, headers=region_admin).status_code == 201
    dup = client.post(
        f"{API}/users",
        json={"name": "Второй Человек", "role": "urbanist", "position": "Спец", "iin": "900202300222"},
        headers=region_admin,
    )
    assert dup.status_code == 409, dup.text
    j = dup.json()
    assert (j.get("code") or j.get("detail", {}).get("code")) == "iin_duplicate"


# ── A-BE-2: единый поиск владельцев и бизнесов ──────────────────────────
def test_owner_search_finds_business_by_bin(client, region_admin):
    client.post(
        f"{API}/owners",
        json={"name": "ТОО Поиск Тест", "legalForm": "ТОО", "phone": "+77010002222", "bin": "180640099001"},
        headers=region_admin,
    )
    r = client.get(f"{API}/owners/search", params={"q": "180640099001"}, headers=region_admin)
    assert r.status_code == 200, r.text
    body = r.json()
    assert any(b["bin"] == "180640099001" for b in body["businesses"])


def test_owner_search_finds_person_by_name(client, region_admin):
    # Заведение бизнеса авто-создаёт аккаунт-владельца → ищем его по названию.
    client.post(
        f"{API}/owners",
        json={"name": "ТОО Уникальное Имя Xyz", "legalForm": "ТОО", "phone": "+77010003333", "bin": "180640099002"},
        headers=region_admin,
    )
    r = client.get(f"{API}/owners/search", params={"q": "Уникальное Имя Xyz"}, headers=region_admin)
    assert r.status_code == 200, r.text
    body = r.json()
    assert any("Уникальное Имя Xyz" in p["name"] for p in body["owners"])


def test_owner_search_short_query_422(client, region_admin):
    r = client.get(f"{API}/owners/search", params={"q": "1"}, headers=region_admin)
    assert r.status_code == 422, r.text


# ── B-BE-2: реальный геокодер (nominatim) маппит адрес ──────────────────
def test_reverse_geocode_nominatim_maps_address(client, urbanist, monkeypatch):
    from app import config
    from app.services import geocoder

    monkeypatch.setattr(config, "GEOCODER_PROVIDER", "nominatim")
    geocoder._cache.clear()

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"display_name": "ул. Абая, 42, Атырау", "address": {"road": "улица Абая", "house_number": "42"}}

    monkeypatch.setattr(geocoder.httpx, "get", lambda *a, **k: FakeResp())
    r = client.get(f"{API}/geocode/reverse", params={"lat": 47.1, "lng": 51.9}, headers=urbanist)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["street"] == "улица Абая"
    assert body["house"] == "42"
    assert body["confidence"] == "high"
