#!/usr/bin/env python3
"""Backfill product_size_id for allegro_offers using parser (bez API)."""
from __future__ import annotations

from sqlalchemy import text

from magazyn.db import get_session
from magazyn.factory import create_app
from magazyn.models.allegro import AllegroOffer
from magazyn.parsing import parse_offer_title
from magazyn.services.order_sync import match_product_to_warehouse


def main() -> int:
    app = create_app()
    linked = 0
    still = 0
    unresolved: list[str] = []

    with app.app_context():
        with get_session() as db:
            offers = (
                db.query(AllegroOffer)
                .filter(AllegroOffer.product_size_id.is_(None))
                .order_by(AllegroOffer.publication_status, AllegroOffer.title)
                .all()
            )
            for offer in offers:
                name, color, size = parse_offer_title(offer.title or "")
                ps = match_product_to_warehouse(db, name, color or "", size or "")
                if ps:
                    offer.product_id = ps.product_id
                    offer.product_size_id = ps.id
                    linked += 1
                else:
                    still += 1
                    unresolved.append(
                        f"[{offer.publication_status}] {offer.offer_id} | {offer.title[:70]} "
                        f"| parsed={name!r}/{color!r}/{size!r}"
                    )
            db.commit()

        print(f"linked={linked}, still_unlinked={still}")
        for line in unresolved:
            print("  ", line)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
