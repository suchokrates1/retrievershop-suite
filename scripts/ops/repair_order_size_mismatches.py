#!/usr/bin/env python3
"""Wykryj i napraw historyczne błędne rozmiary pozycji Allegro.

Domyślnie skrypt wyłącznie raportuje. ``--apply`` zmienia wyłącznie przypadki
jednoznaczne: wysłana sprzedaż bez zwrotu, z pojedynczym rekordem Sale na
błędnym rozmiarze oraz z wystarczającym stanem właściwego rozmiaru.

Przykład:
    python scripts/ops/repair_order_size_mismatches.py
    python scripts/ops/repair_order_size_mismatches.py --apply
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from magazyn.db import get_session
from magazyn.domain.financial import FinancialCalculator
from magazyn.factory import create_app
from magazyn.models.orders import Order, OrderProduct
from magazyn.models.products import ProductSize, Sale
from magazyn.parsing import parse_product_info
from magazyn.services.order_sync import match_product_to_warehouse
from magazyn.settings_store import settings_store

WARSAW = ZoneInfo("Europe/Warsaw")
TWOPLACES = Decimal("0.01")
logger = logging.getLogger("repair_order_size_mismatches")


def _timestamp(value: date) -> int:
    return int(datetime.combine(value, time.min, tzinfo=WARSAW).timestamp())


def _expected_product_size(db, order_product: OrderProduct) -> ProductSize | None:
    name, size, color = parse_product_info(
        {
            "name": order_product.name or "",
            # OrderProduct stores the payload as text; historical records may
            # contain an empty string rather than an attribute list.
            "attributes": [],
        }
    )
    if not name or not size:
        return None
    return match_product_to_warehouse(db, name, color, size)


def _describe(order_product: OrderProduct, linked: ProductSize | None, expected: ProductSize) -> str:
    return (
        f"order={order_product.order_id} line={order_product.id} "
        f"linked={linked.id if linked else None}/{linked.size if linked else '-'} "
        f"expected={expected.id}/{expected.size}"
    )


def _move_sale_to_expected_size(
    db,
    sale: Sale,
    wrong_size: ProductSize,
    expected_size: ProductSize,
) -> tuple[bool, str]:
    if sale.quantity_returned:
        return False, "zwrot już powiązany ze sprzedażą"
    if sale.quantity <= 0:
        return False, "nieprawidłowa ilość Sale"
    if expected_size.quantity < sale.quantity:
        return False, (
            f"brak stanu właściwego rozmiaru {expected_size.size}: "
            f"jest {expected_size.quantity}, potrzeba {sale.quantity}"
        )

    # Undo only the value actually deducted from the wrong bucket.  Historic
    # phantom rows normally have cost 0, so this is a no-op for their stock.
    wrong_cost = Decimal(str(sale.purchase_cost or 0))
    if wrong_cost:
        wrong_size.quantity += sale.quantity
        wrong_size.stock_value = Decimal(str(wrong_size.stock_value or 0)) + wrong_cost

    available = expected_size.quantity
    stock_value = Decimal(str(expected_size.stock_value or 0))
    correct_cost = (
        stock_value * Decimal(sale.quantity) / Decimal(available)
    ).quantize(TWOPLACES, rounding=ROUND_HALF_UP)
    expected_size.quantity -= sale.quantity
    expected_size.stock_value = (
        stock_value - correct_cost if expected_size.quantity else Decimal("0.00")
    )
    sale.product_id = expected_size.product_id
    sale.size = expected_size.size
    sale.purchase_cost = correct_cost
    return True, f"Sale {sale.id}: koszt {wrong_cost:.2f} -> {correct_cost:.2f}"


def audit_and_repair(start: date, end: date, *, apply_changes: bool) -> dict[str, int]:
    stats = {"checked": 0, "mismatches": 0, "repaired": 0, "metadata_only": 0, "skipped": 0}
    start_ts, end_ts = _timestamp(start), _timestamp(end + timedelta(days=1))

    with get_session() as db:
        lines = (
            db.query(OrderProduct)
            .join(Order)
            .filter(
                Order.platform == "allegro",
                Order.date_add >= start_ts,
                Order.date_add < end_ts,
            )
            .order_by(Order.date_add, OrderProduct.id)
            .all()
        )
        calculator = FinancialCalculator(db, settings_store)

        for line in lines:
            stats["checked"] += 1
            linked = line.product_size
            expected = _expected_product_size(db, line)
            if not expected or (linked and linked.id == expected.id):
                continue

            stats["mismatches"] += 1
            logger.info("MISMATCH %s", _describe(line, linked, expected))
            if not linked:
                if apply_changes:
                    line.product_size_id = expected.id
                    calculator.refresh_order_profit_cache(line.order, trace_label="repair-size-mismatch")
                stats["metadata_only"] += 1
                continue

            sales = (
                db.query(Sale)
                .filter(
                    Sale.order_id == line.order_id,
                    Sale.product_id == linked.product_id,
                    Sale.size == linked.size,
                )
                .all()
            )
            if not sales:
                if apply_changes:
                    line.product_size_id = expected.id
                    calculator.refresh_order_profit_cache(line.order, trace_label="repair-size-mismatch")
                stats["metadata_only"] += 1
                continue
            if len(sales) != 1:
                stats["skipped"] += 1
                logger.warning("POMIJAM %s: znaleziono %s rekordów Sale", line.order_id, len(sales))
                continue

            sale = sales[0]
            if not apply_changes:
                logger.info(
                    "DO NAPRAWY %s Sale=%s/%s koszt=%s",
                    _describe(line, linked, expected),
                    sale.id,
                    sale.size,
                    sale.purchase_cost,
                )
                continue

            moved, reason = _move_sale_to_expected_size(db, sale, linked, expected)
            if not moved:
                stats["skipped"] += 1
                logger.warning("POMIJAM %s: %s", line.order_id, reason)
                continue
            line.product_size_id = expected.id
            calculator.refresh_order_profit_cache(line.order, trace_label="repair-size-mismatch")
            stats["repaired"] += 1
            logger.info("NAPRAWIONO %s; %s", line.order_id, reason)

        if apply_changes:
            db.commit()
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, default=date(2026, 6, 1))
    parser.add_argument("--end", type=date.fromisoformat, default=date(2026, 7, 12))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.end < args.start:
        parser.error("--end musi być nie wcześniejszy niż --start")

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    app = create_app()
    with app.app_context():
        stats = audit_and_repair(args.start, args.end, apply_changes=args.apply)
    logger.info("PODSUMOWANIE: %s", stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
