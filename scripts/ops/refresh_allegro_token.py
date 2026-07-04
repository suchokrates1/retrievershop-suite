#!/usr/bin/env python3
"""Odswiez token Allegro w settings_store (PostgreSQL) przed backupem bazy.

Po przywroceniu backupu aplikacja ma w tabeli settings swiezy access token
i refresh token gotowe do dzialania od razu (bez czekania na scheduler ani
recznej autoryzacji OAuth).

Uzycie (lokalnie / w kontenerze magazyn):
    python scripts/ops/refresh_allegro_token.py
    python scripts/ops/refresh_allegro_token.py --dry-run

W kontenerze produkcyjnym:
    docker exec retrievershop-magazyn python3 /app/scripts/ops/refresh_allegro_token.py
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from magazyn.allegro_api.tokens import refresh_allegro_token
from magazyn.factory import create_app
from magazyn.settings_store import settings_store

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("refresh_allegro_token")


def refresh(*, dry_run: bool = False) -> int:
    app = create_app()
    with app.app_context():
        settings_store.reload()
        refresh_token = settings_store.get("ALLEGRO_REFRESH_TOKEN")
        if not refresh_token:
            logger.warning(
                "Brak ALLEGRO_REFRESH_TOKEN w bazie - pomijam odswiezenie "
                "(backup bedzie bez swiezego tokenu Allegro)"
            )
            return 0

        if dry_run:
            logger.info("DRY-RUN: refresh token Allegro (bez zapisu do API)")
            return 0

        try:
            new_access = refresh_allegro_token(refresh_token)
        except RuntimeError as exc:
            logger.error("Nie udalo sie odswiezyc tokenu Allegro: %s", exc)
            return 1

        logger.info(
            "Token Allegro odswiezony i zapisany w bazie (access ...%s)",
            new_access[-8:] if len(new_access) >= 8 else "***",
        )
        return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Sprawdz obecnos refresh tokena bez wywolania API Allegro",
    )
    args = parser.parse_args()
    sys.exit(refresh(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
