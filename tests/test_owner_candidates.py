"""Кандидаты-владельцы по названию объекта — GET /objects/{id}/owner-candidates."""
from __future__ import annotations

from app.services.owner_match import candidates, score

API = "/api/v1"


def test_score_ignores_opf_and_type():
    # «Кафе Ромашка» и «ТОО Ромашка» совпадают по значимому токену.
    assert score("Кафе Ромашка", "ТОО Ромашка") == 1.0
    assert score("Магазин Береке", "Береке Маркет") == 1.0
    assert score("Кафе Уют", "ТОО Другое") == 0.0


def test_candidates_endpoint_matches_by_name(client, region_admin):
    # Заводим владельца-бизнес с узнаваемым названием.
    client.post(f"{API}/owners",
                json={"name": "ТОО Ромашка", "legalForm": "ТОО", "phone": "+77010000123", "bin": "180940011223"},
                headers=region_admin)
    # Создаём объект с похожим названием (region_admin видит все объекты).
    obj = client.post(f"{API}/objects",
                      json={"name": "Кафе Ромашка", "type": "Объект", "lat": 51.2, "lng": 51.37},
                      headers=region_admin).json()
    r = client.get(f"{API}/objects/{obj['id']}/owner-candidates", headers=region_admin)
    assert r.status_code == 200, r.text
    names = [o["name"] for o in r.json()]
    assert "ТОО Ромашка" in names
    assert "Собственник не установлен" not in names  # технического владельца не предлагаем
