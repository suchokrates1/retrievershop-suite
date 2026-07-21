#!/usr/bin/env python3
"""Force-refresh Allegro + orders trust snapshot."""
from __future__ import annotations

import json
import sys

sys.path.insert(0, "/app")

from magazyn.factory import create_app
from magazyn.services.allegro_ratings_snapshot import sync_ratings_snapshot


def main() -> int:
    app = create_app()
    with app.app_context():
        snap = sync_ratings_snapshot(force=True)
    print(json.dumps(snap, ensure_ascii=False, indent=2))
    open("/tmp/rs_allegro_trust.json", "w", encoding="utf-8").write(
        json.dumps(snap, ensure_ascii=False)
    )
    print("wrote /tmp/rs_allegro_trust.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
