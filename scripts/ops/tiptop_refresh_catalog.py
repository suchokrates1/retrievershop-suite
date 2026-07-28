#!/usr/bin/env python3
"""Odswiez katalog TipTop24 (Truelove) — HTTP scrape.

Live probe / trudniejsze strony: kontener price-checker-chrome na minipc
(CDP 192.168.31.5:9222-9223), ten sam co scraper cen Allegro.

Uzycie (z katalogu repo):
  python scripts/ops/tiptop_refresh_catalog.py
  python scripts/ops/tiptop_refresh_catalog.py --max-pages 3 --max-products 20
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running without installing the package
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Refresh TipTop Truelove catalog cache")
    parser.add_argument("--max-pages", type=int, default=8)
    parser.add_argument("--max-products", type=int, default=200)
    args = parser.parse_args(argv)

    from magazyn.db import configure_engine, get_session
    from magazyn.services.tiptop_catalog import refresh_truelove_catalog

    configure_engine()
    with get_session() as db:
        result = refresh_truelove_catalog(
            db,
            max_pages=args.max_pages,
            max_products=args.max_products,
        )

    print(
        f"products={result.products_upserted} variants={result.variants_upserted} "
        f"links+={result.links_created} links~={result.links_updated} "
        f"errors={len(result.errors)}"
    )
    for err in result.errors[:20]:
        print(f"ERR: {err}", file=sys.stderr)
    return 1 if result.errors and result.products_upserted == 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
