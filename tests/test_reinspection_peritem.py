"""Повторная проверка по пунктам: закрытие/продление предписания + лог (tail 2).

o5 в сиде — объект с открытым (overdue) предписанием и статусом,
допускающим повторную проверку.
"""
from __future__ import annotations

API = "/api/v1"
OID = "o5"


def _prescriptions(client, headers):
    return [p for p in client.get(f"{API}/prescriptions", headers=headers).json() if p["objectId"] == OID]


def test_reinspect_all_fixed_closes_prescription(client, region_admin):
    r = client.post(f"{API}/objects/{OID}/reinspections",
                    json={"result": "fixed", "fixed": ["Фасад", "Вывеска"], "remaining": []}, headers=region_admin)
    assert r.status_code == 200, r.text
    assert any(p["status"] == "fixed" for p in _prescriptions(client, region_admin))


def test_reinspect_partial_extends_and_logs(client, region_admin):
    before = _prescriptions(client, region_admin)
    old_deadline = before[0]["deadline"] if before else None
    r = client.post(f"{API}/objects/{OID}/reinspections",
                    json={"result": "partial", "fixed": ["Фасад"], "remaining": ["Вывеска не устранена"]},
                    headers=region_admin)
    assert r.status_code == 200, r.text
    prescs = _prescriptions(client, region_admin)
    # Осталось попало в описание, предписание всё ещё открыто, срок сдвинут.
    assert any(p["status"] in ("open", "overdue") and "Вывеска" in (p["description"] or "") for p in prescs)
    if old_deadline:
        assert any(p["deadline"] != old_deadline for p in prescs)
    # Лог с разбивкой по пунктам (не «тупо продлено»).
    hist = client.get(f"{API}/history", headers=region_admin).json()
    texts = " ".join(h["text"] for h in hist if h["objectId"] == OID and h["type"] == "reinspection")
    assert "устранено 1 из 2" in texts.lower()
