"""Audyt i naprawa ofert Allegro z blednym rozmiarem (np. XXL -> Uniwersalny).

Domyslnie dry-run. Zastosowanie:
  python scripts/ops/_repair_offer_size_mismatches.py
  python scripts/ops/_repair_offer_size_mismatches.py --apply
  python scripts/ops/_repair_offer_size_mismatches.py --apply --fix-orders

Na prod:
  docker exec -e PYTHONPATH=/app -w /app retrievershop-magazyn \\
    python /tmp/_repair_offer_size_mismatches.py [--apply] [--fix-orders]
"""
from __future__ import annotations

import argparse
import sys
from decimal import Decimal

from magazyn.db import configure_engine, get_session
from magazyn.domain.financial import FinancialCalculator
from magazyn.models.allegro import AllegroOffer
from magazyn.models.orders import Order, OrderProduct
from magazyn.models.products import Product, ProductSize, Sale
from magazyn.parsing import parse_offer_title
from magazyn.services.order_sync import match_product_to_warehouse
from magazyn.settings_store import settings_store


def _soft_skip(product: Product | None, parsed_size: str, linked_size: str) -> bool:
    """Smycz/amortyzator/pas czesto maja Uniwersalny w mag. mimo rozmiaru w tytule."""
    if not product:
        return False
    cat = (product.category or "").strip().casefold()
    name = (product.name or "").strip().casefold()
    soft_cats = {
        "smycz",
        "amortyzator",
        "saszetki",
        "pas bezpieczenstwa",
        "pas samochodowy",
    }
    if cat in soft_cats or any(x in name for x in ("smycz", "amortyzator", "pas ")):
        if linked_size.casefold() == "uniwersalny":
            return True
        if parsed_size.casefold() == "uniwersalny":
            return True
    return False


def _repair_order_links(
    db,
    offer_id: str,
    old_ps: ProductSize,
    new_ps: ProductSize,
    *,
    apply: bool,
) -> list[str]:
    notes: list[str] = []
    ops = (
        db.query(OrderProduct)
        .filter(OrderProduct.auction_id == str(offer_id))
        .all()
    )
    for op in ops:
        changed = False
        if op.product_size_id == old_ps.id:
            notes.append(
                f"  OrderProduct id={op.id} order={op.order_id}: "
                f"ps {old_ps.id}->{new_ps.id}"
            )
            if apply:
                op.product_size_id = new_ps.id
            changed = True
        elif op.product_size_id is None:
            notes.append(
                f"  OrderProduct id={op.id} order={op.order_id}: set ps={new_ps.id}"
            )
            if apply:
                op.product_size_id = new_ps.id
            changed = True

        sales = (
            db.query(Sale)
            .filter(Sale.order_id == op.order_id)
            .all()
        )
        for sale in sales:
            same_product = sale.product_id == old_ps.product_id
            same_size = (sale.size or "").upper() == (old_ps.size or "").upper()
            if not (same_product and same_size):
                continue
            avg = None
            if new_ps.quantity and new_ps.stock_value:
                avg = Decimal(str(new_ps.stock_value)) / Decimal(str(new_ps.quantity))
            from magazyn.models.products import PurchaseBatch
            from sqlalchemy import desc

            if avg is None:
                batch = (
                    db.query(PurchaseBatch)
                    .filter(
                        PurchaseBatch.product_id == new_ps.product_id,
                        PurchaseBatch.size == new_ps.size,
                    )
                    .order_by(desc(PurchaseBatch.purchase_date))
                    .first()
                )
                if batch:
                    avg = Decimal(str(batch.price))
            if avg is None:
                notes.append(
                    f"  Sale id={sale.id}: brak kosztu dla {new_ps.size}, skip"
                )
                continue
            qty = int(sale.quantity or 1)
            new_cost = (avg * qty).quantize(Decimal("0.01"))
            notes.append(
                f"  Sale id={sale.id}: size {sale.size}->{new_ps.size}, "
                f"cost {sale.purchase_cost}->{new_cost}"
            )
            if apply:
                sale.product_id = new_ps.product_id
                sale.size = new_ps.size
                sale.purchase_cost = new_cost
            changed = True

        if changed and apply:
            order = db.query(Order).filter(Order.order_id == op.order_id).first()
            if order:
                FinancialCalculator(db, settings_store).refresh_order_profit_cache(
                    order, trace_label="repair-size"
                )
                notes.append(f"  refreshed profit cache for {op.order_id}")
    return notes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--fix-orders",
        action="store_true",
        help="Popraw tez OrderProduct/Sale/profit dla aukcji z remapowanym size",
    )
    parser.add_argument(
        "--status",
        default="ACTIVE",
        help="Filtr publication_status (domyslnie ACTIVE; ALL = bez filtra)",
    )
    args = parser.parse_args()

    configure_engine()
    fixed = 0
    skipped = 0
    no_match = 0

    with get_session() as db:
        q = db.query(AllegroOffer)
        if args.status.upper() != "ALL":
            q = q.filter(AllegroOffer.publication_status == args.status.upper())
        offers = q.all()

        print(f"offers_scanned={len(offers)} apply={args.apply}")
        for offer in offers:
            if not offer.product_size_id:
                continue
            ps = db.query(ProductSize).filter(ProductSize.id == offer.product_size_id).first()
            if not ps or not ps.product:
                continue

            pname, pcolor, psize = parse_offer_title(offer.title or "")
            if not psize:
                continue
            if (psize or "").casefold() == (ps.size or "").casefold():
                continue
            if _soft_skip(ps.product, psize, ps.size or ""):
                skipped += 1
                continue

            rematch = match_product_to_warehouse(db, pname, pcolor, psize)
            if not rematch:
                no_match += 1
                print(
                    f"NO_MATCH offer={offer.offer_id} title={offer.title!r} "
                    f"linked={ps.size} parsed={psize} name={pname!r} color={pcolor!r}"
                )
                continue
            if rematch.id == ps.id:
                skipped += 1
                continue

            rp = rematch.product
            print(
                f"{'APPLY' if args.apply else 'DRY'} offer={offer.offer_id} "
                f"{ps.id}/{ps.size} -> {rematch.id}/{rematch.size} "
                f"product={rp.id if rp else None} {(rp.series if rp else '')!r}/"
                f"{(rp.color if rp else '')!r} | {offer.title}"
            )
            if args.apply:
                offer.product_size_id = rematch.id
                if rp:
                    offer.product_id = rp.id
            fixed += 1

            if args.fix_orders:
                for note in _repair_order_links(
                    db, str(offer.offer_id), ps, rematch, apply=args.apply
                ):
                    print(note)

        if args.apply:
            db.commit()

    print(
        f"done fixed={fixed} soft_skipped={skipped} no_match={no_match} "
        f"mode={'APPLY' if args.apply else 'DRY'}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
