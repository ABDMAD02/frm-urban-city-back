"""Волна 3: архив бизнеса (A-BE-6), отвязка владельца (A-BE-5), импорт объектов (B-BE-4)."""
from __future__ import annotations

import io

API = "/api/v1"


def _make_owner(client, region_admin, bin_="180740088001", name="ТОО Архив Тест"):
    r = client.post(
        f"{API}/owners",
        json={"name": name, "legalForm": "ТОО", "phone": "+77010007777", "bin": bin_},
        headers=region_admin,
    )
    assert r.status_code == 201, r.text
    return r.json()["owner"]


# ── A-BE-6: архив бизнеса ───────────────────────────────────────────────
def test_archive_owner_removes_from_list(client, region_admin):
    owner = _make_owner(client, region_admin, bin_="180740088010")
    assert client.delete(f"{API}/owners/{owner['id']}", headers=region_admin).status_code == 200
    listed = client.get(f"{API}/owners", headers=region_admin).json()
    assert all(o["id"] != owner["id"] for o in listed)


def test_archive_owner_blocked_with_objects(client, region_admin, urbanist):
    owner = _make_owner(client, region_admin, bin_="180740088011")
    # Урбанист ставит объект на этого владельца.
    obj = client.post(
        f"{API}/objects",
        json={"name": "Ларёк", "type": "Объект", "lat": 51.2, "lng": 51.37, "ownerId": owner["id"]},
        headers=urbanist,
    )
    assert obj.status_code == 201, obj.text
    r = client.delete(f"{API}/owners/{owner['id']}", headers=region_admin)
    assert r.status_code == 409, r.text
    j = r.json()
    assert (j.get("code") or j.get("detail", {}).get("code")) == "owner_has_objects"


# ── A-BE-5: отвязка владельца (ownerUserId=null) ────────────────────────
def test_unlink_owner_account(client, region_admin):
    owner = _make_owner(client, region_admin, bin_="180740088012")
    assert owner["ownerUserId"]
    r = client.patch(
        f"{API}/owners/{owner['id']}",
        json={"name": owner["name"], "legalForm": "ТОО", "phone": "+77010007777", "bin": "180740088012", "ownerUserId": None},
        headers=region_admin,
    )
    assert r.status_code == 200, r.text
    assert r.json()["ownerUserId"] is None


# ── B-BE-4: массовый импорт объектов ────────────────────────────────────
def test_import_objects_csv(client, urbanist):
    csv = "name,type,lat,lng\nСклад №1,Объект,51.21,51.38\nСклад №2,Объект,51.22,51.39\n"
    files = {"file": ("objects.csv", io.BytesIO(csv.encode("utf-8")), "text/csv")}
    r = client.post(f"{API}/objects/import-file", files=files, headers=urbanist)
    assert r.status_code == 200, r.text
    assert r.json()["created"] == 2


def test_import_objects_dedup(client, urbanist):
    csv = "name,type,lat,lng\nДубль,Объект,51.25,51.30\nДубль,Объект,51.25,51.30\n"
    files = {"file": ("o.csv", io.BytesIO(csv.encode("utf-8")), "text/csv")}
    r = client.post(f"{API}/objects/import-file", files=files, headers=urbanist)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] == 1 and body["skipped"] == 1


def test_import_objects_geojson(client, urbanist):
    gj = (
        '{"type":"FeatureCollection","features":['
        '{"type":"Feature","geometry":{"type":"Point","coordinates":[51.41,51.28]},'
        '"properties":{"name":"Гео Объект","type":"Объект"}}]}'
    )
    files = {"file": ("o.geojson", io.BytesIO(gj.encode("utf-8")), "application/geo+json")}
    r = client.post(f"{API}/objects/import-file", files=files, headers=urbanist)
    assert r.status_code == 200, r.text
    assert r.json()["created"] == 1
