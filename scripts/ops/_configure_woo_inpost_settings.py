"""Configure WOO_* / INPOST_* in magazyn settings_store.

Reads env vars (do not hardcode secrets in repo).
"""
from __future__ import annotations

import os
import sys


def main() -> int:
    from magazyn.settings_store import settings_store

    required = [
        "WOO_URL",
        "WOO_CONSUMER_KEY",
        "WOO_CONSUMER_SECRET",
        "WOO_WEBHOOK_SECRET",
        "INPOST_TOKEN",
        "INPOST_ORGANIZATION_ID",
    ]
    updates = {}
    missing = []
    for key in required:
        value = os.environ.get(key, "").strip()
        if not value:
            missing.append(key)
        else:
            updates[key] = value
    if missing:
        print("Missing env:", ", ".join(missing), file=sys.stderr)
        return 1
    settings_store.update(updates)
    print("Updated settings:", ", ".join(sorted(updates)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
