"""Разбор файлов географии в канонический GeoImportRequest.

Поддерживаемые форматы файла (авто-детект по расширению/содержимому, можно
переопределить параметром ``fmt``):

  • JSON — два вида:
      – плоский:      {"districts":[{name}], "microdistricts":[{name,districtName?}],
                       "streets":[{name,districtName?,microdistrictName?}]}
      – иерархический:{"districts":[{name, microdistricts:[{name, streets:[...]}]}]}
                       (тот вид, что отдаёт UI супер-админки)
  • CSV / TSV — таблица с заголовком. Колонки распознаются гибко (регистр и язык):
      район/district, микрорайон·мкр/microdistrict, улица/street.
      Каждая строка добавляет присутствующие уровни; связи — по имени.

Результат — плоский ``GeoImportRequest`` со связями по имени; наполнение и дедуп
делает store.import_region_geo (в проде резолвит имена→id).
"""
from __future__ import annotations

import csv
import io
import json

from app.models import (
    GeoImportDistrict,
    GeoImportMicrodistrict,
    GeoImportRequest,
    GeoImportStreet,
)


class GeoImportParseError(ValueError):
    """Файл не удалось разобрать — отдаётся клиенту как 422."""


# Псевдонимы колонок таблицы (нижний регистр, без пробелов по краям).
_DISTRICT_ALIASES = {"district", "districtname", "район", "district_name"}
_MICRODISTRICT_ALIASES = {"microdistrict", "microdistrictname", "микрорайон", "мкр", "microdistrict_name"}
_STREET_ALIASES = {"street", "streetname", "улица", "street_name"}

_JSON_EXT = {".json"}
_TSV_EXT = {".tsv"}
_CSV_EXT = {".csv", ".txt"}


def parse_geo_file(filename: str, content: bytes, fmt: str | None = None) -> GeoImportRequest:
    """Разобрать содержимое файла в GeoImportRequest. Кидает GeoImportParseError."""
    text = _decode(content)
    resolved = _detect_format(filename, fmt, text)
    if resolved == "json":
        return _from_json(text)
    delimiter = "\t" if resolved == "tsv" else _sniff_delimiter(text)
    return _from_delimited(text, delimiter)


def _decode(content: bytes) -> str:
    # utf-8-sig снимает BOM, который Excel добавляет к CSV.
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            return content.decode("cp1251")
        except UnicodeDecodeError as e:
            raise GeoImportParseError("Не удалось прочитать файл: неизвестная кодировка") from e


def _detect_format(filename: str, fmt: str | None, text: str) -> str:
    if fmt:
        f = fmt.strip().lower()
        if f in {"json", "csv", "tsv"}:
            return f
        raise GeoImportParseError(f"Неизвестный формат «{fmt}» (ожидается json, csv или tsv)")
    ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    if ext in _JSON_EXT:
        return "json"
    if ext in _TSV_EXT:
        return "tsv"
    if ext in _CSV_EXT:
        return "csv"
    # Без расширения — угадываем по первому непустому символу.
    stripped = text.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        return "json"
    return "csv"


def _sniff_delimiter(text: str) -> str:
    sample = "\n".join(text.splitlines()[:5])
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t").delimiter
    except csv.Error:
        # Частый случай RU-Excel — точка с запятой; иначе запятая.
        return ";" if sample.count(";") > sample.count(",") else ","


# ── JSON ──────────────────────────────────────────────────────────

def _from_json(text: str) -> GeoImportRequest:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise GeoImportParseError(f"Некорректный JSON: {e}") from e

    districts = data if isinstance(data, list) else data.get("districts")
    if not isinstance(districts, list):
        raise GeoImportParseError("В JSON нет массива districts")

    # Иерархический, если у элементов есть вложенные microdistricts/streets.
    hierarchical = any(
        isinstance(d, dict) and ("microdistricts" in d or "streets" in d) for d in districts
    )
    if hierarchical:
        return _flatten_hierarchical(districts)

    # Плоский вид: microdistricts/streets лежат на верхнем уровне.
    if not isinstance(data, dict):
        raise GeoImportParseError("Плоский JSON должен быть объектом с districts/microdistricts/streets")
    return GeoImportRequest(
        districts=[GeoImportDistrict(name=_req_name(d)) for d in districts],
        microdistricts=[
            GeoImportMicrodistrict(
                name=_req_name(m),
                districtId=m.get("districtId"),
                districtName=m.get("districtName"),
            )
            for m in data.get("microdistricts", [])
        ],
        streets=[
            GeoImportStreet(
                name=_req_name(s),
                districtId=s.get("districtId"),
                districtName=s.get("districtName"),
                microdistrictId=s.get("microdistrictId"),
                microdistrictName=s.get("microdistrictName"),
            )
            for s in data.get("streets", [])
        ],
    )


def _flatten_hierarchical(districts: list) -> GeoImportRequest:
    out_d: list[GeoImportDistrict] = []
    out_m: list[GeoImportMicrodistrict] = []
    out_s: list[GeoImportStreet] = []
    for d in districts:
        d_name = _req_name(d)
        out_d.append(GeoImportDistrict(name=d_name))
        # Улицы могут висеть прямо на районе (без микрорайона).
        for st in d.get("streets", []) or []:
            out_s.append(GeoImportStreet(name=_str_name(st), districtName=d_name))
        for m in d.get("microdistricts", []) or []:
            m_name = _req_name(m)
            out_m.append(GeoImportMicrodistrict(name=m_name, districtName=d_name))
            for st in m.get("streets", []) or []:
                out_s.append(
                    GeoImportStreet(name=_str_name(st), districtName=d_name, microdistrictName=m_name)
                )
    return GeoImportRequest(districts=out_d, microdistricts=out_m, streets=out_s)


def _req_name(item) -> str:
    if not isinstance(item, dict):
        raise GeoImportParseError("Ожидался объект с полем name")
    name = (item.get("name") or "").strip()
    if not name:
        raise GeoImportParseError("Пустое поле name")
    return name


def _str_name(street) -> str:
    # Улица в иерархии может быть строкой или объектом {name}.
    if isinstance(street, str):
        name = street.strip()
    else:
        name = _req_name(street)
    if not name:
        raise GeoImportParseError("Пустое имя улицы")
    return name


# ── CSV / TSV ─────────────────────────────────────────────────────

def _from_delimited(text: str, delimiter: str) -> GeoImportRequest:
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    if not reader.fieldnames:
        raise GeoImportParseError("Пустой файл — нет строки заголовка")

    colmap = _map_columns(reader.fieldnames)
    if not colmap:
        raise GeoImportParseError(
            "Не найдено ни одной колонки район/микрорайон/улица в заголовке"
        )

    seen_d: set[str] = set()
    seen_m: set[str] = set()
    seen_s: set[str] = set()
    out_d: list[GeoImportDistrict] = []
    out_m: list[GeoImportMicrodistrict] = []
    out_s: list[GeoImportStreet] = []

    for row in reader:
        d_name = _cell(row, colmap.get("district"))
        m_name = _cell(row, colmap.get("microdistrict"))
        s_name = _cell(row, colmap.get("street"))

        if d_name and d_name.lower() not in seen_d:
            seen_d.add(d_name.lower())
            out_d.append(GeoImportDistrict(name=d_name))
        if m_name and m_name.lower() not in seen_m:
            seen_m.add(m_name.lower())
            out_m.append(GeoImportMicrodistrict(name=m_name, districtName=d_name or None))
        if s_name and s_name.lower() not in seen_s:
            seen_s.add(s_name.lower())
            out_s.append(
                GeoImportStreet(
                    name=s_name,
                    districtName=d_name or None,
                    microdistrictName=m_name or None,
                )
            )

    if not (out_d or out_m or out_s):
        raise GeoImportParseError("В файле нет ни одной записи географии")
    return GeoImportRequest(districts=out_d, microdistricts=out_m, streets=out_s)


def _map_columns(fieldnames: list[str]) -> dict[str, str]:
    """Сопоставить реальные заголовки с логическими уровнями (по псевдонимам)."""
    out: dict[str, str] = {}
    for raw in fieldnames:
        if raw is None:
            continue
        key = raw.strip().lower()
        if key in _DISTRICT_ALIASES and "district" not in out:
            out["district"] = raw
        elif key in _MICRODISTRICT_ALIASES and "microdistrict" not in out:
            out["microdistrict"] = raw
        elif key in _STREET_ALIASES and "street" not in out:
            out["street"] = raw
    return out


def _cell(row: dict, column: str | None) -> str:
    if not column:
        return ""
    return (row.get(column) or "").strip()
