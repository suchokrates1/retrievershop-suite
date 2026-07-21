#!/usr/bin/env python3
"""Dograj description_html dla ofert ENDED bez tresci (limit batch)."""
from __future__ import annotations

import os
import sys

os.environ.setdefault("DISABLE_SCHEDULERS", "1")

from magazyn.db import get_session
from magazyn.factory import create_app
from magazyn.models.allegro import AllegroOffer
from magazyn.services.allegro_offer_content import sync_offer_content

LIMIT = int(sys.argv[1]) if len(sys.argv) > 1 else 80


def main() -> None:
    app = create_app()
    ok = fail = skip = 0
    with app.app_context():
        with get_session() as db:
            rows = (
                db.query(AllegroOffer)
                .filter(AllegroOffer.publication_status == "ENDED")
                .filter(
                    (AllegroOffer.description_html.is_(None))
                    | (AllegroOffer.description_html == "")
                )
                .order_by(AllegroOffer.synced_at.desc().nullslast())
                .limit(LIMIT)
                .all()
            )
            print(f"candidates={len(rows)} limit={LIMIT}")
            for offer in rows:
                try:
                    sync_offer_content(offer.offer_id, force=True)
                    db.refresh(offer)
                    if (offer.description_html or "").strip():
                        ok += 1
                        print(f"OK {offer.offer_id}")
                    else:
                        skip += 1
                        print(f"EMPTY {offer.offer_id}")
                except Exception as exc:  # noqa: BLE001
                    fail += 1
                    print(f"FAIL {offer.offer_id}: {exc}")
            db.commit()
    print(f"done ok={ok} empty={skip} fail={fail}")


if __name__ == "__main__":
    main()
