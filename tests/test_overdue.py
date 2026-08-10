"""«По истечении срока — просрочено» (находка P1: срок никогда не истекал).

Статус overdue выставлялся только в сиде; deadline с датой не сравнивался, поэтому
любое реальное открытое уведомление оставалось open навечно, а эскалация в налоговую
и KPI «просрочено» были нерабочими.
"""
from __future__ import annotations

from app.domain_rules import effective_prescription_status
from app.enums import PrescriptionStatus

API = "/api/v1"


def test_domain_rule():
    Open, Overdue = PrescriptionStatus.open, PrescriptionStatus.overdue
    # открытое + прошедший дедлайн → overdue
    assert effective_prescription_status(Open, "2026-06-01", "2026-07-02") == Overdue
    # открытое + будущий дедлайн → как есть
    assert effective_prescription_status(Open, "2026-12-31", "2026-07-02") == Open
    # дедлайн ровно сегодня → ещё не просрочено
    assert effective_prescription_status(Open, "2026-07-02", "2026-07-02") == Open
    # не-open не трогаем
    assert effective_prescription_status(PrescriptionStatus.fixed, "2020-01-01", "2026-07-02") == PrescriptionStatus.fixed
    assert effective_prescription_status(PrescriptionStatus.closed, "2020-01-01", "2026-07-02") == PrescriptionStatus.closed


def _make_open_overdue_prescription(client, urbanist, region_admin) -> str:
    """Провести проверку с замечаниями → авто-уведомление (open) → сдвинуть срок в прошлое."""
    body = {
        "inspection": {
            "id": "", "objectId": "o2", "inspector": "Айгерим Нурланова",
            "date": "2026-07-02", "result": "has_remarks", "checklist": [],
            "comment": "", "photoIds": [],
        },
        "status": "prescription_issued",
        "photos": [{"id": "", "objectId": "o2", "kind": "before", "caption": "",
                    "date": "2026-07-02", "author": "Айгерим Нурланова"}],
    }
    r = client.post(f"{API}/objects/o2/inspections", json=body, headers=urbanist)
    assert r.status_code == 201, r.text
    pid = r.json()["prescription"]["id"]
    assert r.json()["prescription"]["status"] == "open"
    # админ сдвигает срок в прошлое (статус остаётся open)
    p = client.patch(f"{API}/prescriptions/{pid}", json={"deadline": "2026-06-01"}, headers=region_admin)
    assert p.status_code == 200, p.text
    return pid


def test_open_past_deadline_reads_as_overdue(client, urbanist, region_admin):
    pid = _make_open_overdue_prescription(client, urbanist, region_admin)
    got = client.get(f"{API}/prescriptions/{pid}", headers=region_admin)
    assert got.status_code == 200, got.text
    assert got.json()["status"] == "overdue", "открытое с прошедшим сроком должно читаться как overdue"


def test_overdue_counts_in_analytics_and_notifications(client, urbanist, region_admin):
    before = client.get(f"{API}/analytics/summary", headers=region_admin).json()["overdue"]
    _make_open_overdue_prescription(client, urbanist, region_admin)
    after = client.get(f"{API}/analytics/summary", headers=region_admin).json()["overdue"]
    assert after == before + 1, "KPI overdue должен вырасти"

    notes = client.get(f"{API}/notifications", headers=region_admin).json()
    assert any(n["type"] == "prescription_overdue" for n in notes)
