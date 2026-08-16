"""Режим импорта географии: append (по умолч.) vs replace."""
from __future__ import annotations

from tests.conftest import API

BASE = f"{API}/platform/regions/uralsk"


def _districts(client, headers):
    return [d["name"] for d in client.get(f"{BASE}/districts", headers=headers).json()]


def test_append_keeps_existing(client, superadmin):
    before = _districts(client, superadmin)
    assert len(before) >= 1  # уральск засеян демо-гео
    payload = {"districts": [{"name": "ДопРайонXYZ"}], "microdistricts": [], "streets": []}
    r = client.post(f"{BASE}/geo/import", headers=superadmin, json=payload)  # default append
    assert r.status_code == 200, r.text
    after = _districts(client, superadmin)
    assert "ДопРайонXYZ" in after
    assert set(before).issubset(set(after))  # старое на месте


def test_replace_wipes_then_fills(client, superadmin):
    before = _districts(client, superadmin)
    assert len(before) >= 1
    payload = {"districts": [{"name": "ЗаменаРайон"}], "microdistricts": [], "streets": []}
    r = client.post(f"{BASE}/geo/import?mode=replace", headers=superadmin, json=payload)
    assert r.status_code == 200, r.text
    after = _districts(client, superadmin)
    assert after == ["ЗаменаРайон"]  # старое стёрто, осталось только из файла


def test_bad_mode_422(client, superadmin):
    r = client.post(f"{BASE}/geo/import?mode=nuke", headers=superadmin, json={"districts": []})
    assert r.status_code == 422
