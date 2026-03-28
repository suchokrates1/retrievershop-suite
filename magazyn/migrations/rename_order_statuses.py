"""
Migration: Rename legacy order statuses to new unified names.
Date: 2026-03-28
Description: Zmienia stare nazwy statusow w tabeli order_status_logs
na nowe, spojne nazwy z status_config.py.

Mapowanie:
  niewydrukowano → pobrano
  przekazano_kurierowi → wyslano
  w_drodze → wyslano
  gotowe_do_odbioru → w_punkcie
  niedostarczono → problem_z_dostawa
  zagubiono → problem_z_dostawa
  awizo → w_punkcie
  zakończono → dostarczono

Uruchamiac PO wdrozeniu kodu (legacy fallback w UI chroni podczas przejscia).
Wykonano na produkcji: 2026-03-28 (191 wierszy zaktualizowanych).
"""

import os
import sys

# Dodaj sciezke projektu aby mozna bylo importowac modul
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import text
from db import SessionLocal


RENAME_MAP = {
    "niewydrukowano": "pobrano",
    "przekazano_kurierowi": "wyslano",
    "w_drodze": "wyslano",
    "gotowe_do_odbioru": "w_punkcie",
    "niedostarczono": "problem_z_dostawa",
    "zagubiono": "problem_z_dostawa",
    "awizo": "w_punkcie",
    "zakończono": "dostarczono",
    "zakonczono": "dostarczono",  # wariant bez polskich znakow
}


def migrate():
    """Rename legacy statuses in order_status_logs (PostgreSQL)."""
    db = SessionLocal()

    try:
        total_updated = 0
        for old_status, new_status in RENAME_MAP.items():
            result = db.execute(
                text("UPDATE order_status_logs SET status = :new WHERE status = :old"),
                {"new": new_status, "old": old_status},
            )
            count = result.rowcount
            if count:
                print(f"  {old_status} -> {new_status}: {count} wierszy")
                total_updated += count

        db.commit()
        print(f"[OK] Zaktualizowano {total_updated} wierszy lacznie w order_status_logs")
    except Exception as e:
        db.rollback()
        print(f"[BLAD] {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    migrate()
