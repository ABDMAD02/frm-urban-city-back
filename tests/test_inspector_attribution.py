"""Проверка привязана к сотруднику по id и датируется сервером (редизайн, честные данные).

Раньше `inspector` был только строкой-именем, `inspector_id` — мёртвой колонкой, а дату
брали с клиента. Теперь сервер ставит inspector/inspectorId/date из JWT — основа для
личной выработки урбаниста и «активности урбанистов».
"""
from __future__ import annotations

API = "/api/v1"


def _inspect(client, headers, oid="o2", date_from_client="2000-01-01"):
    body = {
        "inspection": {
            "id": "", "objectId": oid, "inspector": "ПОДДЕЛКА", "inspectorId": "u999",
            "date": date_from_client, "result": "has_remarks", "checklist": [],
            "comment": "", "photoIds": [],
        },
        "status": "prescription_issued",
        "photos": [{"id": "", "objectId": oid, "kind": "before", "caption": "",
                    "date": "2026-07-02", "author": "x"}],
    }
    return client.post(f"{API}/objects/{oid}/inspections", json=body, headers=headers)


def test_inspector_and_date_set_by_server(client, urbanist):
    # клиент прислал чужое имя/id и дату 2000 — сервер перезаписывает своими
    r = _inspect(client, urbanist)
    assert r.status_code == 201, r.text
    insp = r.json()["inspection"]
    assert insp["inspector"] == "Айгерим Нурланова"       # имя из JWT, не «ПОДДЕЛКА»
    assert insp["inspectorId"] == "u1"                    # id из JWT, не «u999»
    assert insp["date"] == "2026-07-02"                   # серверная дата (DEMO_TODAY), не 2000


def test_inspection_appears_in_list_with_inspector_id(client, urbanist, region_admin):
    _inspect(client, urbanist, oid="o10")
    lst = client.get(f"{API}/inspections", headers=region_admin).json()
    mine = [i for i in lst if i.get("inspectorId") == "u1"]
    assert mine, "проверка должна быть в списке с inspectorId=u1"
