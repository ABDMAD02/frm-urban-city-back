"""Батч-импорт бизнесов из госреестра: endpoint POST /owners/import + парсер egov."""
from __future__ import annotations

from app.enums import LegalForm
from app.services import egov

API = "/api/v1"


# ── Endpoint: record-only, дедуп, опц. телефон, роль ──────────────
def test_import_creates_record_only(client, region_admin):
    r = client.post(
        f"{API}/owners/import",
        json={"items": [
            {"name": "ТОО «Импорт-1»", "legalForm": "ТОО", "bin": "010203040506"},
            {"name": "ТОО «Импорт-2»", "legalForm": "ТОО", "bin": "060504030201"},
        ]},
        headers=region_admin,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] == 2
    assert body["skipped"] == 0
    assert len(body["createdOwnerIds"]) == 2

    # Аккаунты-владельцы НЕ созданы: ownerUserId остаётся пустым.
    owners = client.get(f"{API}/owners", headers=region_admin).json()
    imported = [o for o in owners if o["bin"] in ("010203040506", "060504030201")]
    assert len(imported) == 2
    assert all(o["ownerUserId"] is None for o in imported)


def test_import_skips_duplicate_bin(client, region_admin):
    # 180140012345 уже есть в сиде (w1); второй дубль — внутри батча.
    r = client.post(
        f"{API}/owners/import",
        json={"items": [
            {"name": "Дубль сида", "legalForm": "ТОО", "bin": "180140012345"},
            {"name": "Новый", "legalForm": "ТОО", "bin": "111122223333"},
            {"name": "Дубль в батче", "legalForm": "ТОО", "bin": "111122223333"},
        ]},
        headers=region_admin,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] == 1
    assert body["skipped"] == 2


def test_import_allows_missing_phone(client, region_admin):
    r = client.post(
        f"{API}/owners/import",
        json={"items": [{"name": "Без телефона", "legalForm": "ТОО", "bin": "222233334444"}]},
        headers=region_admin,
    )
    assert r.status_code == 200, r.text
    assert r.json()["created"] == 1
    owners = client.get(f"{API}/owners", headers=region_admin).json()
    imported = next(o for o in owners if o["bin"] == "222233334444")
    assert imported["phone"] is None


def test_import_requires_region_admin(client, urbanist):
    r = client.post(
        f"{API}/owners/import",
        json={"items": [{"name": "X", "legalForm": "ТОО"}]},
        headers=urbanist,
    )
    assert r.status_code == 403, r.text


def test_import_rejects_invalid_bin(client, region_admin):
    r = client.post(
        f"{API}/owners/import",
        json={"items": [{"name": "Кривой БИН", "legalForm": "ТОО", "bin": "123"}]},
        headers=region_admin,
    )
    assert r.status_code == 422, r.text  # валидация схемы OwnerImportItem


# ── Парсер egov: чистые функции ───────────────────────────────────
def test_map_legal_form():
    assert egov.map_legal_form("Товарищество с ограниченной ответственностью «X»") == LegalForm.too
    assert egov.map_legal_form("Государственное учреждение «Аппарат акимата»") == LegalForm.gosorgan
    assert egov.map_legal_form("Коммунальное государственное учреждение «Школа №1»") == LegalForm.gosorgan
    assert egov.map_legal_form("Акционерное общество «Y»") == LegalForm.too  # фолбэк (enum узкий)


def test_record_to_item():
    raw = {
        "nameru": "ТОО «Тест»",
        "bin": "180140012345",
        "addressru": "090000, ЗАПАДНО-КАЗАХСТАНСКАЯ ОБЛАСТЬ, Г.УРАЛЬСК",
        "statusru": "Зарегистрирован",
    }
    item = egov.record_to_item(raw)
    assert item is not None
    assert item.bin == "180140012345"
    assert item.legalForm == LegalForm.too
    assert item.phone is None

    assert egov.record_to_item({"nameru": ""}) is None            # нет имени
    assert egov.record_to_item({"nameru": "X", "bin": "123"}) is None  # кривой БИН → пропуск


def test_iter_legal_entities_region_filter_and_pagination():
    """Фиктивный httpx.Client: 1 страница из 3 записей, фильтр по региону."""
    import httpx

    page = [
        {"nameru": "ТОО «Уральск-1»", "bin": "100000000001",
         "addressru": "ЗАПАДНО-КАЗАХСТАНСКАЯ ОБЛАСТЬ, Г.УРАЛЬСК", "statusru": "Зарегистрирован"},
        {"nameru": "ТОО «Алматы-1»", "bin": "100000000002",
         "addressru": "Г.АЛМАТЫ", "statusru": "Зарегистрирован"},
        {"nameru": "ТОО «Уральск-2»", "bin": "100000000003",
         "addressru": "ЗКО, Г.УРАЛЬСК", "statusru": "Ликвидирован"},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        # вторая страница пустая → конец
        if '"from": 0' in request.url.params.get("source", ""):
            return httpx.Response(200, json=page)
        return httpx.Response(200, json=[])

    transport = httpx.MockTransport(handler)
    from app import config
    config.EGOV_OPENDATA_API_KEY = "test-key"
    with httpx.Client(transport=transport) as fake:
        items = list(egov.iter_legal_entities(
            region_filter="УРАЛЬСК", page_size=3, client=fake,
        ))
    # Алматы отфильтрован по региону, «Ликвидирован» — по статусу.
    assert [i.bin for i in items] == ["100000000001"]
