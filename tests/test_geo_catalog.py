"""Каталог городов РК: полнота сида + эндпоинт со списком (с кодом)."""
from __future__ import annotations

from app.geo_catalog import GEO_CATALOG_CITIES, catalog_city_summary
from tests.conftest import API


def test_catalog_has_20_cities_with_unique_codes():
    assert len(GEO_CATALOG_CITIES) == 20
    codes = [c["code"] for c in GEO_CATALOG_CITIES]
    assert all(codes), "у каждого города должен быть code"
    assert len(set(codes)) == 20, "коды городов уникальны"
    ids = [c["id"] for c in GEO_CATALOG_CITIES]
    assert len(set(ids)) == 20, "id городов уникальны"


def test_catalog_entries_have_center_and_schema():
    for c in GEO_CATALOG_CITIES:
        cfg = c["config"]
        assert cfg["addressSchema"]
        assert cfg.get("centerLat") is not None and cfg.get("centerLng") is not None


def test_summary_exposes_code():
    s = catalog_city_summary(GEO_CATALOG_CITIES[0])
    assert s["code"] == GEO_CATALOG_CITIES[0]["code"]


def test_catalog_endpoint_lists_cities_with_code(client, superadmin):
    r = client.get(f"{API}/platform/geo-catalog/cities", headers=superadmin)
    assert r.status_code == 200, r.text
    cities = r.json()
    assert len(cities) == 20
    astana = next((c for c in cities if c["code"] == "astana"), None)
    assert astana is not None and astana["name"] == "Астана"


def test_provision_from_catalog_city(client, superadmin):
    # Провижн Караганды из каталога → регион создаётся, гео-конфиг из каталога.
    body = {
        "code": "karaganda",
        "name": "Караганда",
        "adminName": "Тест Админ",
        "geo": {"source": "catalog", "cityCatalogId": "kz-karaganda"},
    }
    r = client.post(f"{API}/platform/regions", headers=superadmin, json=body)
    assert r.status_code == 201, r.text
    region = r.json()["region"]
    assert region["code"] == "karaganda"
