#!/usr/bin/env python3
"""Kontrola spojnosci wyceny magazynu (srednia wazona / AVCO).

Po przejsciu na wycene metoda sredniej wazonej stan magazynu opisuja dwie
wielkosci na ``ProductSize``: ``quantity`` i ``stock_value`` (laczna wartosc
zakupu sztuk na stanie). Musi zachodzic inwariant:

    stock_value >= 0   oraz   quantity == 0  =>  stock_value == 0
    quantity > 0       =>      stock_value >= 0

Ten skrypt wyszukuje wiersze lamiace inwariant (ujemna wartosc, wartosc przy
zerowym stanie). Domyslnie tylko raportuje; z ``--fix`` zeruje wartosc tam,
gdzie ``quantity == 0`` i zeruje ujemne wartosci (log kazdej korekty).

Uzycie:
    python scripts/ops/reconcile_stock_value.py
    python scripts/ops/reconcile_stock_value.py --fix
"""
from __future__ import annotations

import argparse
import logging
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from magazyn.factory import create_app
from magazyn.db import get_session
from magazyn.models.products import ProductSize

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("reconcile_stock_value")


def _check(fix: bool) -> int:
    violations = 0
    fixed = 0
    with get_session() as db:
        rows = db.query(ProductSize).all()
        for ps in rows:
            qty = ps.quantity or 0
            value = Decimal(str(ps.stock_value or 0))

            bad_zero = qty == 0 and value != 0
            bad_negative = value < 0
            if not (bad_zero or bad_negative):
                continue

            violations += 1
            logger.info(
                "NIESPOJNOSC ps_id=%s product_id=%s size=%s quantity=%s stock_value=%s%s%s",
                ps.id,
                ps.product_id,
                ps.size,
                qty,
                value,
                " [wartosc przy zerowym stanie]" if bad_zero else "",
                " [ujemna wartosc]" if bad_negative else "",
            )

            if fix:
                if bad_zero or bad_negative and qty == 0:
                    ps.stock_value = Decimal("0.00")
                elif bad_negative:
                    ps.stock_value = Decimal("0.00")
                fixed += 1

    logger.info(
        "Zakonczono: niespojnosci=%s%s",
        violations,
        f", naprawiono={fixed}" if fix else " (tryb raportu, uzyj --fix aby poprawic)",
    )
    return violations


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fix", action="store_true", help="Zeruj niespojne wartosci")
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        violations = _check(args.fix)
    sys.exit(1 if violations and not args.fix else 0)


if __name__ == "__main__":
    main()
