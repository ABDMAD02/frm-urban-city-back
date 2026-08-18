"""Парсер открытого реестра юрлиц РК (data.egov.kz, датасет ``gbd_ul``).

Тянет записи постранично, фильтрует по региону и маппит в
:class:`~app.models.OwnerImportItem`. Вызывается офлайн-скриптом
``scripts/import_owners_egov.py`` — НЕ из request-пути (полный скан
национального реестра долгий).

Особенности источника (проверено на публичном ключе):
* серверный ES-фильтр (``source.query``) игнорируется → фильтруем по региону
  локально, по подстроке адреса;
* постраничное смещение (``from``) может не соблюдаться → есть защита от
  зацикливания (break при отсутствии новых БИН на странице);
* телефонов и e-mail в реестре нет;
* ИП списком недоступны (юр. ограничение) — датасет только по юрлицам.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Iterator

import httpx

from app import config
from app.enums import LegalForm
from app.models import OwnerImportItem

logger = logging.getLogger(__name__)

# Статусы «действующего» юрлица (ru/kz) — активные записи реестра.
_ACTIVE_STATUSES = ("зарегистрирован", "действ", "тіркелді", "әрекет")

# Маркеры государственных структур в наименовании → LegalForm.gosorgan.
_GOV_MARKERS = (
    "государственн", "коммуналь", "казённ", "казенн", "акимат", "әкімдік",
    "маслихат", "мәслихат", "министерство", "министрлі", "департамент",
    "управление", "басқарма", "учреждение", "мекеме", "ведомство",
)


def map_legal_form(name: str) -> LegalForm:
    """Определить ОПФ по наименованию юрлица.

    Enum узкий (ИП/ТОО/Физлицо/Госорган); прочие формы (АО/ОО/ПК/фонд…)
    консервативно относим к ``ТОО``. Расширение справочника ОПФ — follow-up.
    """
    low = (name or "").lower()
    if low.startswith("ип ") or "индивидуальный предприниматель" in low or "жеке кәсіпкер" in low:
        return LegalForm.ip
    if any(marker in low for marker in _GOV_MARKERS):
        return LegalForm.gosorgan
    return LegalForm.too


def record_to_item(raw: dict) -> OwnerImportItem | None:
    """Одна запись ``gbd_ul`` → OwnerImportItem. ``None`` — запись непригодна."""
    name = (raw.get("nameru") or raw.get("namekz") or "").strip()
    if not name:
        return None
    bin_value = (raw.get("bin") or "").strip() or None
    try:
        return OwnerImportItem(
            name=name,
            legalForm=map_legal_form(name),
            bin=bin_value,
            phone=None,   # телефонов в реестре нет
            email=None,
        )
    except Exception as exc:  # невалидный БИН и т.п.
        logger.debug("skip egov record bin=%s: %s", bin_value, exc)
        return None


def _region_matches(raw: dict, region_filter: str | None) -> bool:
    if not region_filter:
        return True
    needle = region_filter.strip().lower()
    hay = f"{raw.get('addressru', '')} {raw.get('addresskz', '')}".lower()
    return needle in hay


def _is_active(raw: dict, active_only: bool) -> bool:
    if not active_only:
        return True
    status = f"{raw.get('statusru', '')} {raw.get('statuskz', '')}".strip().lower()
    if not status:
        return True
    return any(s in status for s in _ACTIVE_STATUSES)


def iter_legal_entities(
    *,
    region_filter: str | None = None,
    limit: int | None = None,
    active_only: bool = True,
    page_size: int | None = None,
    max_pages: int = 10_000,
    client: httpx.Client | None = None,
) -> Iterator[OwnerImportItem]:
    """Постранично тянуть юрлиц из ``gbd_ul`` и маппить в OwnerImportItem.

    :param region_filter: подстрока адреса (напр. ``ЗАПАДНО-КАЗАХСТАНСКАЯ`` или
        ``УРАЛЬСК``); ``None`` — без фильтра (вся РК).
    :param limit: максимум годных (отфильтрованных) записей на выходе.
    :param active_only: пропускать нединамические/ликвидированные записи.
    :param client: внешний ``httpx.Client`` (для тестов/переиспользования).
    """
    if not config.EGOV_OPENDATA_API_KEY:
        raise RuntimeError("EGOV_OPENDATA_API_KEY не задан")

    size = page_size or config.EGOV_OPENDATA_PAGE_SIZE
    base = config.EGOV_OPENDATA_API_BASE
    dataset = config.EGOV_OPENDATA_DATASET
    version = config.EGOV_OPENDATA_DATASET_VERSION
    url = f"{base}/{dataset}/{version}" if version else f"{base}/{dataset}"

    own_client = client is None
    cl = client or httpx.Client(timeout=config.EGOV_OPENDATA_TIMEOUT)
    yielded = 0
    seen_bins: set[str] = set()
    offset = 0
    no_progress = 0
    try:
        for _ in range(max_pages):
            resp = cl.get(url, params={
                "apiKey": config.EGOV_OPENDATA_API_KEY,
                "source": json.dumps({"size": size, "from": offset}),
            })
            resp.raise_for_status()
            rows = resp.json()
            if not isinstance(rows, list) or not rows:
                break

            new_bins_on_page = 0
            for raw in rows:
                if not _region_matches(raw, region_filter):
                    continue
                if not _is_active(raw, active_only):
                    continue
                item = record_to_item(raw)
                if item is None:
                    continue
                if item.bin:
                    if item.bin in seen_bins:
                        continue
                    seen_bins.add(item.bin)
                    new_bins_on_page += 1
                yield item
                yielded += 1
                if limit and yielded >= limit:
                    return

            # Защита от игнорируемого сервером `from`: если страница не дала
            # ни одного нового БИН — считаем, что листания нет, выходим.
            if new_bins_on_page == 0:
                no_progress += 1
                if no_progress >= 2:
                    logger.warning("egov: нет прогресса пагинации на offset=%s — стоп", offset)
                    break
            else:
                no_progress = 0

            if len(rows) < size:
                break
            offset += size
    finally:
        if own_client:
            cl.close()
