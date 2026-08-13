"""Импорт географии файлом: парсер (JSON/CSV/TSV) + эндпоинт /geo/import-file."""
from __future__ import annotations

import json

import pytest

from app.geo_import import GeoImportParseError, parse_geo_file
from tests.conftest import API


# ── Парсер ────────────────────────────────────────────────────────

def _parse(name: str, text: str, fmt=None):
    return parse_geo_file(name, text.encode("utf-8"), fmt)


def test_json_hierarchical():
    text = json.dumps(
        {"districts": [{"name": "Р1", "microdistricts": [{"name": "М1", "streets": ["У1", "У2"]}]}]}
    )
    req = _parse("geo.json", text)
    assert [d.name for d in req.districts] == ["Р1"]
    assert req.microdistricts[0].districtName == "Р1"
    assert [s.name for s in req.streets] == ["У1", "У2"]
    assert req.streets[0].microdistrictName == "М1"


def test_json_flat():
    text = json.dumps(
        {
            "districts": [{"name": "Р1"}],
            "microdistricts": [{"name": "М1", "districtName": "Р1"}],
            "streets": [{"name": "У1", "districtName": "Р1", "microdistrictName": "М1"}],
        }
    )
    req = _parse("geo.json", text)
    assert len(req.districts) == 1 and len(req.microdistricts) == 1 and len(req.streets) == 1


def test_json_hierarchical_streets_on_district():
    text = json.dumps({"districts": [{"name": "Р1", "streets": ["У1"]}]})
    req = _parse("geo.json", text)
    assert req.streets[0].districtName == "Р1"
    assert req.streets[0].microdistrictName is None


def test_csv_semicolon_ru_headers():
    text = "район;микрорайон;улица\nЦентр;Мкр А;ул. Первая\nЦентр;Мкр А;ул. Вторая\nЦентр;Мкр Б;ул. Третья\n"
    req = _parse("geo.csv", text)
    assert len(req.districts) == 1  # дедуп «Центр»
    assert {m.name for m in req.microdistricts} == {"Мкр А", "Мкр Б"}
    assert len(req.streets) == 3
    assert req.streets[0].districtName == "Центр"


def test_tsv_en_headers():
    text = "district\tstreet\nD1\tS1\n"
    req = _parse("geo.tsv", text)
    assert len(req.districts) == 1 and len(req.streets) == 1 and len(req.microdistricts) == 0


def test_format_override_beats_extension():
    text = "district,street\nD1,S1\n"
    req = _parse("geo.txt", text, fmt="csv")
    assert len(req.districts) == 1


def test_bad_format_raises():
    with pytest.raises(GeoImportParseError):
        _parse("geo.xml", "<geo/>", fmt="xml")


def test_garbage_json_raises():
    with pytest.raises(GeoImportParseError):
        _parse("geo.json", "{not json")


def test_csv_without_known_columns_raises():
    with pytest.raises(GeoImportParseError):
        _parse("geo.csv", "foo,bar\n1,2\n")


# ── Эндпоинт ──────────────────────────────────────────────────────

IMPORT_URL = f"{API}/platform/regions/uralsk/geo/import-file"


def test_import_file_endpoint_csv(client, superadmin):
    csv = (
        "район;микрорайон;улица\n"
        "ФайлТестРайон;ФайлТестМкр;ФайлТест ул. Один\n"
        "ФайлТестРайон;ФайлТестМкр;ФайлТест ул. Два\n"
    ).encode("utf-8")
    r = client.post(
        IMPORT_URL,
        headers=superadmin,
        files={"file": ("geo.csv", csv, "text/csv")},
    )
    assert r.status_code == 200, r.text
    added = r.json()["added"]
    assert added == {"districts": 1, "microdistricts": 1, "streets": 2}

    # Записи реально появились в регионе.
    names = [d["name"] for d in client.get(f"{API}/platform/regions/uralsk/districts", headers=superadmin).json()]
    assert "ФайлТестРайон" in names


def test_import_file_endpoint_json_hierarchical(client, superadmin):
    payload = json.dumps(
        {"districts": [{"name": "JРайон", "microdistricts": [{"name": "JМкр", "streets": ["Jул1"]}]}]}
    ).encode("utf-8")
    r = client.post(
        IMPORT_URL,
        headers=superadmin,
        files={"file": ("geo.json", payload, "application/json")},
    )
    assert r.status_code == 200, r.text
    assert r.json()["added"] == {"districts": 1, "microdistricts": 1, "streets": 1}


def test_import_file_bad_content_422(client, superadmin):
    r = client.post(
        IMPORT_URL,
        headers=superadmin,
        files={"file": ("geo.json", b"{broken", "application/json")},
    )
    assert r.status_code == 422
    assert r.json()["code"] == "geo_import_parse_error"


def test_import_file_requires_superadmin(client):
    r = client.post(
        IMPORT_URL,
        files={"file": ("geo.csv", b"district\nD1\n", "text/csv")},
    )
    assert r.status_code in (401, 403)
