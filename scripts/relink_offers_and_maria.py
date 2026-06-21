#!/usr/bin/env python3
"""Relink Allegro offers + order_products bez EAN (kategoria/kolor/rozmiar)."""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text

from magazyn.allegro_sync import sync_offers
from magazyn.db import get_session
from magazyn.domain.inventory import consume_order_stock
from magazyn.factory import create_app
from magazyn.models.orders import OrderProduct
from magazyn.parsing import parse_product_info
from magazyn.services.order_sync import match_product_to_warehouse

MARIA_ORDER = "allegro_b94d1a60-69ae-11f1-b822-3b889f6dec5e"


def _item_from_order_product(op: OrderProduct) -> dict[str, Any]:
    attrs = op.attributes
    if isinstance(attrs, str):
        try:
            attrs = json.loads(attrs)
        except json.JSONDecodeError:
            attrs = []
    return {
        "name": op.name or "",
        "ean": (op.ean or "").strip(),
        "quantity": op.quantity or 1,
        "price_brutto": op.price_brutto,
        "auction_id": op.auction_id,
        "attributes": attrs or [],
    }


def relink_order_products() -> tuple[int, int]:
    linked = 0
    still_unlinked = 0

    with get_session() as db:
        rows = (
            db.query(OrderProduct)
            .filter(OrderProduct.product_size_id.is_(None))
            .order_by(OrderProduct.order_id)
            .all()
        )
        for op in rows:
            product_size_id = None

            if op.auction_id:
                offer_row = db.execute(
                    text(
                        """
                        SELECT product_size_id
                        FROM allegro_offers
                        WHERE offer_id = :oid AND product_size_id IS NOT NULL
                        """
                    ),
                    {"oid": str(op.auction_id)},
                ).fetchone()
                if offer_row and offer_row[0]:
                    product_size_id = offer_row[0]

            if not product_size_id:
                item = _item_from_order_product(op)
                name, size, color = parse_product_info(item)
                if name and size:
                    ps = match_product_to_warehouse(db, name, color or "", size)
                    if ps:
                        product_size_id = ps.id

            if product_size_id:
                op.product_size_id = product_size_id
                linked += 1
            else:
                still_unlinked += 1
                print(
                    "UNLINKED:",
                    op.order_id,
                    "|",
                    (op.name or "")[:70],
                )

        db.commit()

    return linked, still_unlinked


def backfill_maria_sale() -> None:
    with get_session() as db:
        op = (
            db.query(OrderProduct)
            .filter(
                OrderProduct.order_id == MARIA_ORDER,
                OrderProduct.product_size_id.isnot(None),
            )
            .first()
        )
        if not op:
            print("Maria order_product still unlinked")
            return

        sale = db.execute(
            text(
                """
                SELECT s.id FROM sales s
                JOIN product_sizes ps ON ps.product_id = s.product_id AND ps.size = s.size
                WHERE ps.id = :psid
                  AND s.sale_date >= '2026-06-16'
                LIMIT 1
                """
            ),
            {"psid": op.product_size_id},
        ).fetchone()
        if sale:
            print("Maria sale already exists:", sale[0])
            return

        item = _item_from_order_product(op)
        if op.ean:
            item["ean"] = op.ean

    consume_order_stock([item])
    print("Maria consume_order_stock executed for", item["name"][:60])


def main() -> int:
    app = create_app()
    with app.app_context():
        print("=== Sync Allegro offers (parser: kategoria + kolor + rozmiar) ===")
        result = sync_offers()
        print("sync_offers:", result)

        print("\n=== Relink order_products (product_size_id IS NULL) ===")
        linked, still = relink_order_products()
        print(f"linked={linked}, still_unlinked={still}")

        print("\n=== Maria kamizelka: stock/sale backfill ===")
        backfill_maria_sale()

        print("\n=== Maria order after relink ===")
        with get_session() as db:
            rows = db.execute(
                text(
                    """
                    SELECT op.name, op.product_size_id, ps.size, p.name, p.color, ps.quantity
                    FROM order_products op
                    LEFT JOIN product_sizes ps ON ps.id = op.product_size_id
                    LEFT JOIN products p ON p.id = ps.product_id
                    WHERE op.order_id = :oid
                    """
                ),
                {"oid": MARIA_ORDER},
            ).fetchall()
            for row in rows:
                print(row)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
