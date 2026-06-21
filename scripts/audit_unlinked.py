#!/usr/bin/env python3
"""Audit unlinked offers/order_products and test parser matching."""
from __future__ import annotations

from sqlalchemy import text

from magazyn.db import get_session
from magazyn.factory import create_app
from magazyn.parsing import parse_offer_title, parse_product_info
from magazyn.services.order_sync import match_product_to_warehouse


def main() -> int:
    app = create_app()
    with app.app_context():
        print("=== UNLINKED ACTIVE/INACTIVE OFFERS ===")
        with get_session() as db:
            offers = db.execute(
                text(
                    """
                    SELECT offer_id, title, publication_status
                    FROM allegro_offers
                    WHERE product_size_id IS NULL
                    ORDER BY publication_status, title
                    """
                )
            ).fetchall()
            for oid, title, status in offers:
                name, color, size = parse_offer_title(title or "")
                ps = match_product_to_warehouse(db, name, color or "", size or "")
                print(
                    f"[{status}] {oid} | {title[:75]}"
                )
                print(
                    f"  -> parsed: {name!r} / {color!r} / {size!r} | "
                    f"match: {ps.id if ps else 'NONE'}"
                )

        print("\n=== UNLINKED ORDER_PRODUCTS ===")
        with get_session() as db:
            ops = db.execute(
                text(
                    """
                    SELECT op.order_id, op.auction_id, op.name
                    FROM order_products op
                    WHERE op.product_size_id IS NULL
                    ORDER BY op.name
                    """
                )
            ).fetchall()
            for order_id, auction_id, name in ops:
                item = {"name": name, "ean": "", "attributes": []}
                pname, psize, pcolor = parse_product_info(item)
                ps = match_product_to_warehouse(db, pname, pcolor or "", psize or "")
                print(f"{order_id} | auction={auction_id}")
                print(f"  {name[:75]}")
                print(
                    f"  -> parsed: {pname!r} / {pcolor!r} / {psize!r} | "
                    f"match: {ps.id if ps else 'NONE'}"
                )

        print("\n=== WAREHOUSE: Smycz / Amortyzator / Saszetka / Kamizelka ===")
        with get_session() as db:
            rows = db.execute(
                text(
                    """
                    SELECT p.id, p.name, p.color, p.series, ps.id AS psid, ps.size
                    FROM products p
                    JOIN product_sizes ps ON ps.product_id = p.id
                    WHERE p.name ILIKE '%smycz%'
                       OR p.name ILIKE '%amortyz%'
                       OR p.name ILIKE '%saszet%'
                       OR p.name ILIKE '%kamizel%'
                       OR p.name ILIKE '%przysmak%'
                    ORDER BY p.name, ps.size
                    """
                )
            ).fetchall()
            for row in rows:
                print(row)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
