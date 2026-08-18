"""Автозаполнение формы бизнеса из гос-реестра: GET /owners/registry-lookup + egov.lookup_by_bin."""
from __future__ import annotations

import httpx
import pytest

from app import config
from app.services import egov

API = "/api/v1"


# ── Сервис: точный поиск по БИН ───────────────────────────────────
def _mock_client(record: dict | None) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[record] if record else [])
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_lookup_by_bin_maps_fields(monkeypatch):
    monkeypatch.setattr(config, "EGOV_OPENDATA_API_KEY", "test-key")
    rec = {
        "bin": "160340010950",
        "nameru": "Товарищество с ограниченной ответственностью «Тест»",
        "addressru": "090000, ЗАПАДНО-КАЗАХСТАНСКАЯ ОБЛАСТЬ, Г.УРАЛЬСК",
        "okedru": "Строительство",
        "director": "ИВАНОВ И.И.",
        "statusru": "Зарегистрирован",
    }
    with _mock_client(rec) as cl:
        found = egov.lookup_by_bin("160340010950", client=cl)
    assert found is not None
    assert found["name"].startswith("Товарищество")
    assert found["legalForm"] == "ТОО"
    assert found["bin"] == "160340010950"
    assert "УРАЛЬСК" in found["address"]
    assert found["oked"] == "Строительство"


def test_lookup_by_bin_defensive_mismatch(monkeypatch):
    # term-фильтр проигнорирован → вернулась чужая запись → None (не подставляем мусор).
    monkeypatch.setattr(config, "EGOV_OPENDATA_API_KEY", "test-key")
    rec = {"bin": "999999999999", "nameru": "Другая фирма"}
    with _mock_client(rec) as cl:
        assert egov.lookup_by_bin("160340010950", client=cl) is None


def test_lookup_by_bin_not_found(monkeypatch):
    monkeypatch.setattr(config, "EGOV_OPENDATA_API_KEY", "test-key")
    with _mock_client(None) as cl:
        assert egov.lookup_by_bin("160340010950", client=cl) is None


# ── Endpoint ──────────────────────────────────────────────────────
def _enable(monkeypatch):
    monkeypatch.setattr(config, "EGOV_OPENDATA_ENABLED", True)
    monkeypatch.setattr(config, "EGOV_OPENDATA_API_KEY", "test-key")


def test_endpoint_ok(client, region_admin, monkeypatch):
    _enable(monkeypatch)
    monkeypatch.setattr(egov, "lookup_by_bin", lambda b: {
        "name": "ТОО «Тест»", "legalForm": "ТОО", "bin": b,
        "address": "Г.УРАЛЬСК", "oked": "Строительство", "director": "ИВАНОВ И.И.", "status": "Зарегистрирован",
    })
    r = client.get(f"{API}/owners/registry-lookup", params={"bin": "160340010950"}, headers=region_admin)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "ТОО «Тест»"
    assert body["legalForm"] == "ТОО"


def test_endpoint_bad_bin(client, region_admin, monkeypatch):
    _enable(monkeypatch)
    r = client.get(f"{API}/owners/registry-lookup", params={"bin": "123"}, headers=region_admin)
    assert r.status_code == 422, r.text


def test_endpoint_disabled(client, region_admin, monkeypatch):
    monkeypatch.setattr(config, "EGOV_OPENDATA_ENABLED", False)
    r = client.get(f"{API}/owners/registry-lookup", params={"bin": "160340010950"}, headers=region_admin)
    assert r.status_code == 503, r.text
    assert r.json()["code"] == "registry_disabled"


def test_endpoint_not_found(client, region_admin, monkeypatch):
    _enable(monkeypatch)
    monkeypatch.setattr(egov, "lookup_by_bin", lambda b: None)
    r = client.get(f"{API}/owners/registry-lookup", params={"bin": "160340010950"}, headers=region_admin)
    assert r.status_code == 404, r.text


def test_endpoint_owner_forbidden(client, owner, monkeypatch):
    _enable(monkeypatch)
    r = client.get(f"{API}/owners/registry-lookup", params={"bin": "160340010950"}, headers=owner)
    assert r.status_code == 403, r.text
