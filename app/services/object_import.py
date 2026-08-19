"""Разбор файла объектов для массовой загрузки (B-BE-4).

Поддерживает CSV и GeoJSON:
* CSV — колонки ``name,type,lat,lng`` + опц. ``bin,address`` (разделитель ,/;/таб
  определяется автоматически);
* GeoJSON — ``FeatureCollection`` с точками ``[lng, lat]`` и свойствами
  ``name/type/bin/address``.

Возвращает список :class:`~app.models.ObjectImportItem`. Дедуп и создание —
на слое стора (по паре координат + названию).
"""
from __future__ import annotations

import json

from app.models import ObjectImportItem


def _num(v) -> float | None:
    try:
        return float(str(v).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None


def _sniff(text: str) -> str:
    head = "\n".join(text.split("\n")[:5])
    tab, semi, comma = head.count("\t"), head.count(";"), head.count(",")
    if tab >= semi and tab >= comma:
        return "\t"
    return ";" if semi > comma else ","


def _from_geojson(data: dict) -> list[ObjectImportItem]:
    out: list[ObjectImportItem] = []
    for feat in data.get("features", []):
        geom = feat.get("geometry") or {}
        if geom.get("type") != "Point":
            continue
        coords = geom.get("coordinates") or []
        if len(coords) < 2:
            continue
        lng, lat = _num(coords[0]), _num(coords[1])
        props = feat.get("properties") or {}
        name = (props.get("name") or "").strip()
        if lat is None or lng is None or not name:
            continue
        out.append(ObjectImportItem(
            name=name,
            type=(props.get("type") or "Объект").strip(),
            lat=lat, lng=lng,
            address=(props.get("address") or None),
            bin=(props.get("bin") or None),
        ))
    return out


def _from_csv(text: str) -> list[ObjectImportItem]:
    lines = [ln for ln in text.replace("﻿", "").split("\n") if ln.strip()]
    if not lines:
        return []
    delim = _sniff(text)
    header = [h.strip().lower() for h in lines[0].split(delim)]
    idx = {key: header.index(key) for key in ("name", "type", "lat", "lng", "bin", "address") if key in header}
    if "name" not in idx or "lat" not in idx or "lng" not in idx:
        raise ValueError("CSV: нужны колонки name, lat, lng")
    out: list[ObjectImportItem] = []
    for line in lines[1:]:
        cells = [c.strip() for c in line.split(delim)]

        def cell(key):
            i = idx.get(key)
            return cells[i] if i is not None and i < len(cells) else None

        lat, lng = _num(cell("lat")), _num(cell("lng"))
        name = (cell("name") or "").strip()
        if lat is None or lng is None or not name:
            continue
        out.append(ObjectImportItem(
            name=name,
            type=(cell("type") or "Объект").strip(),
            lat=lat, lng=lng,
            address=(cell("address") or None),
            bin=(cell("bin") or None),
        ))
    return out


def parse_objects_file(text: str, filename: str = "") -> list[ObjectImportItem]:
    t = text.strip()
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    is_json = ext in ("geojson", "json") or (ext not in ("csv", "tsv") and t.startswith("{"))
    if is_json:
        try:
            data = json.loads(t)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Некорректный GeoJSON: {exc}") from exc
        return _from_geojson(data)
    return _from_csv(t)
