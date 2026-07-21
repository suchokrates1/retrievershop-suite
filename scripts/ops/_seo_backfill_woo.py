"""Backfill Allegro content + Woo catalog titles/images after SEO sync deploy."""
from __future__ import annotations

import json
import os
import sys

os.environ["DISABLE_SCHEDULERS"] = "1"

from magazyn.factory import create_app
from magazyn.services.allegro_offer_content import sync_linked_offers_content
from magazyn.services.woo_catalog_sync import sync_catalog_to_woo


def main() -> int:
    app = create_app()
    with app.app_context():
        content = sync_linked_offers_content(
            limit=120, force=True, include_ended_without_content=True
        )
        print("CONTENT", json.dumps(content, ensure_ascii=False))
        # Full mapped catalog rename + fill empty desc/images
        catalog = sync_catalog_to_woo(limit=300, refresh_content=False)
        print("CATALOG", json.dumps(catalog, ensure_ascii=False))
    return 0 if catalog.get("errors", 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
