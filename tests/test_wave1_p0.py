"""Волна 1 (P0): центр карты в cities/current, честный геокодер, коллизия логина."""
from __future__ import annotations

API = "/api/v1"


# ── B-BE-1: центр карты доходит до клиента ──────────────────────────────
def test_cities_current_includes_map_center(client, region_admin):
    r = client.get(f"{API}/cities/current", headers=region_admin)
    assert r.status_code == 200, r.text
    body = r.json()
    # Поля присутствуют в ответе (клиент центрирует карту по ним).
    for key in ("centerLat", "centerLng", "mapZoom"):
        assert key in body, f"нет поля {key} в cities/current"
    # И совпадают с тем, что отдаёт geo-config того же города.
    cfg = client.get(f"{API}/cities/{body['id']}/geo-config", headers=region_admin).json()
    assert body["centerLat"] == cfg.get("centerLat")
    assert body["centerLng"] == cfg.get("centerLng")
    assert body["mapZoom"] == cfg.get("mapZoom")


# ── B-BE-2: обратный геокодер честно отвечает 503, а не выдумкой ─────────
def test_reverse_geocode_off_returns_503(client, urbanist):
    r = client.get(f"{API}/geocode/reverse", params={"lat": 51.2, "lng": 51.37}, headers=urbanist)
    assert r.status_code == 503, r.text
    # Хендлер уплощает detail → {message, code} на верхнем уровне.
    body = r.json()
    code = body.get("code") or body.get("detail", {}).get("code")
    assert code == "geocoder_unavailable", r.text


# ── A-BE-3: коллизия сгенерированного логина владельца разрешается ──────
def test_owner_login_collision_resolved(client, region_admin):
    # Оба имени дают один логин t.testov (login_for: первая буква имени + фамилия).
    r1 = client.post(
        f"{API}/owners",
        json={"name": "ТОО Тестов", "legalForm": "ТОО", "phone": "+77010000010", "bin": "180540027001"},
        headers=region_admin,
    )
    assert r1.status_code == 201, r1.text
    login1 = r1.json()["credentials"]["login"]

    r2 = client.post(
        f"{API}/owners",
        json={"name": "Тест Тестов", "legalForm": "ИП", "phone": "+77010000011", "bin": "180540027002"},
        headers=region_admin,
    )
    # Раньше падало 422 duplicate из-за занятого логина — теперь 201 с другим логином.
    assert r2.status_code == 201, r2.text
    login2 = r2.json()["credentials"]["login"]

    assert login1 and login2 and login1 != login2
    # Второй логин — тот же базовый + числовой суффикс (t.testov → t.testov2).
    assert login2.startswith(login1)
    assert login2[len(login1):].isdigit()
