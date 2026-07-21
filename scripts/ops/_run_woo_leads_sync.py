#!/usr/bin/env python3
"""One-shot: sync Woo catalog with Allegro-derived leads (no content refresh)."""
from __future__ import annotations

import sys

sys.path.insert(0, "/app")

from magazyn.factory import create_app
from magazyn.services.woo_catalog_sync import sync_catalog_to_woo


def main() -> int:
    app = create_app()
    with app.app_context():
        stats = sync_catalog_to_woo(limit=400, refresh_content=False)
        print("stats", stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
