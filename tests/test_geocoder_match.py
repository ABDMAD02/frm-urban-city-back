"""Сопоставление имени улицы/микрорайона из геокодера → id справочника (B-BE-2)."""
from __future__ import annotations

from types import SimpleNamespace

from app.services.geocoder import _norm, match_ids


def test_norm_strips_types_ru_kk():
    assert _norm("улица Талгата Бигельдинова") == _norm("Талгата Бигельдинова")
    assert _norm("проспект Абая") == "абая"
    assert _norm("микрорайон Жеруйык") == "жеруйык"
    assert _norm("Абая көшесі") == "абая"


def test_match_street_and_microdistrict():
    streets = [
        SimpleNamespace(id="s1", name="ул. Абая", districtId="d1", microdistrictId=None),
        SimpleNamespace(id="s2", name="проспект Достык", districtId="d1", microdistrictId=None),
    ]
    mds = [SimpleNamespace(id="m1", name="мкр Жеруйык", districtId="d1")]

    st, md, d = match_ids("улица Абая", "микрорайон Жеруйык", streets, mds)
    assert st == "s1"
    assert md == "m1"
    assert d == "d1"


def test_match_none_when_no_dictionary_hit():
    st, md, d = match_ids("улица Неизвестная", "мкр Нету", [], [])
    assert (st, md, d) == (None, None, None)
