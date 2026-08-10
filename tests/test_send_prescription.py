"""Выдача уведомления фиксируется честно, без ложного «отправлено по email» (P1).

Раньше POST /prescriptions/{pid}/send всегда возвращал sent:true и писал в историю
«Предписание отправлено», хотя e-mail-канала нет — ложный след в юридически значимом
процессе. Плюс ручка не проверяла роль (владелец мог «выдать» своё уведомление).
"""
from __future__ import annotations

API = "/api/v1"


def test_owner_cannot_send(client, owner):
    r = client.post(f"{API}/prescriptions/pr1/send", json={}, headers=owner)
    assert r.status_code == 403, r.text


def test_send_records_issuance_truthfully(client, region_admin):
    r = client.post(f"{API}/prescriptions/pr1/send", json={"email": "biz@example.kz"}, headers=region_admin)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["to"] == "biz@example.kz"
    assert body["sentAt"]

    # история: фиксация выдачи, без ложного «отправлено»
    audit = client.get(f"{API}/audit", headers=region_admin).json()
    texts = [e["text"] for e in audit if e.get("objectId") == "o5"]
    assert any("Зафиксирована выдача уведомления" in t for t in texts), texts
    assert not any("отправлено" in t.lower() for t in texts), "не должно быть ложного 'отправлено'"
