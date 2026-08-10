"""Тренд проверок считается из реальных дат, а не из статичного сида (редизайн)."""
from __future__ import annotations

from datetime import date

from app.domain_rules import inspection_trend_counts

API = "/api/v1"


def test_trend_counts_pure():
    today = date(2026, 7, 2)
    dates = [date(2026, 7, 1), date(2026, 7, 20), date(2026, 6, 5), date(2026, 1, 1)]
    res = inspection_trend_counts(dates, today, months=6)
    labels = [l for l, _ in res]
    assert labels == ["Фев", "Мар", "Апр", "Май", "Июн", "Июл"]  # последние 6, кончая июлем
    by = dict(res)
    assert by["Июл"] == 2   # две проверки в июле
    assert by["Июн"] == 1
    assert by["Май"] == 0
    # январская дата вне окна 6 месяцев — не считается
    assert sum(v for _, v in res) == 3


def test_trend_endpoint_reflects_real_inspections(client, urbanist, region_admin):
    before = client.get(f"{API}/analytics/inspection-trend", headers=region_admin).json()
    # проведём проверку — серверная дата = DEMO_TODAY (2026-07-02, июль)
    body = {
        "inspection": {"id": "", "objectId": "o2", "inspector": "x", "date": "2026-07-02",
                       "result": "has_remarks", "checklist": [], "comment": "", "photoIds": []},
        "status": "prescription_issued",
        "photos": [{"id": "", "objectId": "o2", "kind": "before", "caption": "",
                    "date": "2026-07-02", "author": "x"}],
    }
    assert client.post(f"{API}/objects/o2/inspections", json=body, headers=urbanist).status_code == 201
    after = client.get(f"{API}/analytics/inspection-trend", headers=region_admin).json()
    # значения — не захардкоженные 8/12/17/14/22/26
    assert [p["value"] for p in after] != [8, 12, 17, 14, 22, 26]
    jul_before = next((p["value"] for p in before if p["month"] == "Июл"), 0)
    jul_after = next((p["value"] for p in after if p["month"] == "Июл"), 0)
    assert jul_after == jul_before + 1
