"""Сев объектов из OpenStreetMap (Overpass) — POST /objects/import-osm."""
from __future__ import annotations

API = "/api/v1"

_FAKE_OVERPASS = {
    "elements": [
        {"type": "node", "lat": 51.21, "lon": 51.38,
         "tags": {"name": "Кафе Уют", "amenity": "cafe", "addr:street": "ул. Абая", "addr:housenumber": "10"}},
        {"type": "way", "center": {"lat": 51.22, "lon": 51.39},
         "tags": {"name": "Магазин Береке", "shop": "supermarket"}},
        {"type": "node", "lat": 51.23, "lon": 51.40, "tags": {"amenity": "pharmacy"}},  # без name — пропускаем
    ]
}


def _patch_overpass(monkeypatch):
    from app.services import osm_poi

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return _FAKE_OVERPASS

    monkeypatch.setattr(osm_poi.httpx, "post", lambda *a, **k: FakeResp())


def _ensure_center(client, region_admin):
    city = client.get(f"{API}/cities/current", headers=region_admin).json()
    client.patch(f"{API}/cities/{city['id']}/geo-config",
                 json={"centerLat": 51.2, "centerLng": 51.37}, headers=region_admin)


def test_import_osm_creates_named_pois(client, region_admin, monkeypatch):
    _ensure_center(client, region_admin)
    _patch_overpass(monkeypatch)
    r = client.post(f"{API}/objects/import-osm?radius_m=8000", headers=region_admin)
    assert r.status_code == 200, r.text
    body = r.json()
    # Две именованные точки создаём, безымянную аптеку пропускаем.
    assert body["created"] == 2


def test_import_osm_requires_admin(client, urbanist, monkeypatch):
    _patch_overpass(monkeypatch)
    r = client.post(f"{API}/objects/import-osm", headers=urbanist)
    assert r.status_code == 403, r.text


def test_import_osm_503_when_overpass_down(client, region_admin, monkeypatch):
    from app.services import osm_poi

    _ensure_center(client, region_admin)

    def boom(*a, **k):
        raise RuntimeError("timeout")

    monkeypatch.setattr(osm_poi.httpx, "post", boom)
    r = client.post(f"{API}/objects/import-osm", headers=region_admin)
    assert r.status_code == 503, r.text
    j = r.json()
    assert (j.get("code") or j.get("detail", {}).get("code")) == "overpass_unavailable"
