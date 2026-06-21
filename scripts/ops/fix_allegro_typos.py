#!/usr/bin/env python3
"""Popraw literówki w tytułach ofert Allegro i przelinkuj."""
from __future__ import annotations

import re

from sqlalchemy import text

from magazyn.allegro_api.offers import change_offer_name
from magazyn.allegro_sync import sync_offers
from magazyn.constants import normalize_product_title_fragment
from magazyn.db import get_session
from magazyn.factory import create_app
from magazyn.models.orders import OrderProduct
from magazyn.parsing import parse_product_info
from magazyn.services.order_sync import match_product_to_warehouse

TITLE_FIXES: list[tuple[str, str]] = [
    (r"\bAmortyaator\b", "Amortyzator"),
    (r"\bamortyaator\b", "amortyzator"),
    (r"\bśrednieho\b", "średniego"),
    (r"\bsrednieho\b", "sredniego"),
    (r"\bpda\b", "psa"),
    (r"\bTuelove\b", "Truelove"),
    (r"\bFrone\b", "Front"),
    (r"\bFron\b", "Front"),
    (r"\bftont\b", "Front"),
]


def fix_title(title: str) -> str:
    result = title or ""
    for pattern, repl in TITLE_FIXES:
        result = re.sub(pattern, repl, result, flags=re.IGNORECASE)
    result = normalize_product_title_fragment(result)
    return re.sub(r"\s+", " ", result).strip()


def relink_order_products() -> tuple[int, int, list[str]]:
    linked = 0
    still = 0
    unresolved: list[str] = []
    with get_session() as db:
        rows = (
            db.query(OrderProduct)
            .filter(OrderProduct.product_size_id.is_(None))
            .all()
        )
        for op in rows:
            product_size_id = None
            if op.auction_id:
                row = db.execute(
                    text(
                        """
                        SELECT product_size_id FROM allegro_offers
                        WHERE offer_id = :oid AND product_size_id IS NOT NULL
                        """
                    ),
                    {"oid": str(op.auction_id)},
                ).fetchone()
                if row and row[0]:
                    product_size_id = row[0]
            if not product_size_id:
                item = {
                    "name": op.name or "",
                    "ean": (op.ean or "").strip(),
                    "attributes": op.attributes or [],
                }
                name, size, color = parse_product_info(item)
                if name and size:
                    ps = match_product_to_warehouse(db, name, color or "", size)
                    if ps:
                        product_size_id = ps.id
            if product_size_id:
                op.product_size_id = product_size_id
                linked += 1
            else:
                still += 1
                unresolved.append(f"{op.order_id} | {op.name}")
        db.commit()
    return linked, still, unresolved


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Wyślij poprawki tytułów do Allegro API")
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        print("=== Tytuły do poprawy na Allegro ===")
        with get_session() as db:
            rows = db.execute(
                text(
                    """
                    SELECT offer_id, title, publication_status
                    FROM allegro_offers
                    WHERE product_size_id IS NULL
                    ORDER BY publication_status, title
                    """
                )
            ).fetchall()
            fixes = []
            for offer_id, title, status in rows:
                old = title or ""
                new = fix_title(old)
                if new == old.strip():
                    continue
                fixes.append((str(offer_id), status, old, new))

        for offer_id, status, old, new in fixes:
            print(f"{offer_id} [{status}]")
            print(f"  BYŁO: {old}")
            print(f"  BĘDZIE: {new}")
            if args.apply and status in {"ACTIVE", "INACTIVE"}:
                resp = change_offer_name(offer_id, new)
                print(f"  API: {'OK' if resp.get('success') else resp.get('error')}")
        print(f"fixes={len(fixes)}")

        if args.apply:
            print("\n=== sync_offers ===")
            print(sync_offers())

        print("\n=== relink order_products ===")
        linked, still, unresolved = relink_order_products()
        print(f"linked={linked}, still_unlinked={still}")
        for line in unresolved:
            print("  UNLINKED:", line[:100])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
