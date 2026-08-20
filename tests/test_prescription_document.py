"""Официальный документ предписания — GET /prescriptions/{id}/document."""
from __future__ import annotations

API = "/api/v1"


def _first_pid(client, headers):
    items = client.get(f"{API}/prescriptions", headers=headers).json()
    assert items, "нет предписаний в сиде"
    return items[0]["id"]


def test_prescription_document_html(client, region_admin):
    pid = _first_pid(client, region_admin)
    r = client.get(f"{API}/prescriptions/{pid}/document", headers=region_admin)
    assert r.status_code == 200, r.text
    assert "text/html" in r.headers["content-type"]
    body = r.text
    assert "ПРЕДПИСАНИЕ" in body
    assert pid in body                      # номер предписания в документе
    assert "срок до" in body.lower()


def test_prescription_document_404(client, region_admin):
    r = client.get(f"{API}/prescriptions/nope-xxx/document", headers=region_admin)
    assert r.status_code == 404, r.text


def test_prescription_document_pdf(client, region_admin):
    pid = _first_pid(client, region_admin)
    r = client.get(f"{API}/prescriptions/{pid}/document.pdf", headers=region_admin)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    assert r.content[:5] == b"%PDF-"          # валидная PDF-сигнатура
    assert len(r.content) > 1000
