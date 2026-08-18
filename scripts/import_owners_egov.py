#!/usr/bin/env python3
"""Офлайн-раннер: импорт бизнесов из data.egov.kz (gbd_ul) в регион.

Тянет юрлиц через app.services.egov (парсер на бэке), фильтрует по региону
и льёт в API `POST {base}/owners/import` чанками под токеном админа региона.

Запуск (из корня репозитория):
    EGOV_OPENDATA_API_KEY=... python -m scripts.import_owners_egov \
        --base-url https://<host>/api/v1 \
        --token <region_admin access JWT> \
        --region-filter "ЗАПАДНО-КАЗАХСТАНСКАЯ" \
        --limit 500

`--dry-run` — только распечатать нормализованные записи (без запроса к API),
удобно оценить объём и качество маппинга.
"""
from __future__ import annotations

import argparse
import json
import sys

import httpx

from app.services import egov


def _chunks(seq: list, size: int):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Импорт бизнесов из data.egov.kz gbd_ul")
    p.add_argument("--base-url", help="База API, напр. https://host/api/v1")
    p.add_argument("--token", help="Access JWT админа региона (region_admin)")
    p.add_argument("--region-filter", default=None,
                   help="Подстрока адреса (напр. 'ЗАПАДНО-КАЗАХСТАНСКАЯ' или 'УРАЛЬСК')")
    p.add_argument("--limit", type=int, default=None, help="Максимум записей")
    p.add_argument("--chunk-size", type=int, default=500, help="Размер чанка для POST")
    p.add_argument("--all-statuses", action="store_true", help="Не отсеивать по статусу")
    p.add_argument("--dry-run", action="store_true", help="Только распечатать записи, без импорта")
    args = p.parse_args(argv)

    items = list(egov.iter_legal_entities(
        region_filter=args.region_filter,
        limit=args.limit,
        active_only=not args.all_statuses,
    ))
    print(f"[egov] получено записей: {len(items)}", file=sys.stderr)

    if args.dry_run:
        for it in items:
            print(json.dumps(it.model_dump(), ensure_ascii=False))
        return 0

    if not args.base_url or not args.token:
        p.error("для импорта нужны --base-url и --token (или используйте --dry-run)")

    url = args.base_url.rstrip("/") + "/owners/import"
    headers = {"Authorization": f"Bearer {args.token}"}
    totals = {"created": 0, "skipped": 0, "failed": 0}
    with httpx.Client(timeout=60) as client:
        for chunk in _chunks(items, args.chunk_size):
            payload = {"items": [it.model_dump() for it in chunk]}
            resp = client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            res = resp.json()
            totals["created"] += res.get("created", 0)
            totals["skipped"] += res.get("skipped", 0)
            totals["failed"] += len(res.get("failed", []))
            print(f"[import] chunk={len(chunk)} → {res.get('created', 0)} создано, "
                  f"{res.get('skipped', 0)} пропущено", file=sys.stderr)

    print(f"[import] ИТОГО: создано={totals['created']} пропущено={totals['skipped']} "
          f"ошибок={totals['failed']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
