#!/usr/bin/env python3
"""Backfill AllegroOffer.product_size_id dla ofert linkowanych dotychczas
tylko na poziomie produktu (Faza 3 migracji, patrz plan
"Migracja produktow i uproszczenie dopasowan").

Po Fazie 2 (audit_product_sizes.py --apply) kazdy produkt powinien miec
albo dokladnie jeden aktywny wariant (single-SKU / "Uniwersalny"), albo kilka
wariantow rozmiarowych. Ten skrypt znajduje AllegroOffer z ustawionym
product_id, ale bez product_size_id, i:

- jesli produkt ma dokladnie 1 wiersz ProductSize -> uzupelnia
  product_size_id automatycznie (jednoznaczne dopasowanie),
- jesli produkt ma 0 lub >1 wierszy ProductSize -> zostawia ofere bez zmian
  i wypisuje ja na liscie "do recznego dowiazania".

Domyslnie tylko raportuje (zero zapisow). Uzycie:
    python scripts/ops/backfill_offer_product_size.py
    python scripts/ops/backfill_offer_product_size.py --apply
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from magazyn.db import get_session
from magazyn.factory import create_app
from magazyn.models.allegro import AllegroOffer
from magazyn.models.products import ProductSize

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("backfill_offer_product_size")


def backfill(apply_changes: bool) -> dict[str, int]:
    stats = {"linked": 0, "ambiguous": 0, "no_sizes": 0}

    with get_session() as db:
        offers = (
            db.query(AllegroOffer)
            .filter(
                AllegroOffer.product_id.isnot(None),
                AllegroOffer.product_size_id.is_(None),
            )
            .order_by(AllegroOffer.id)
            .all()
        )

        for offer in offers:
            sizes = (
                db.query(ProductSize)
                .filter_by(product_id=offer.product_id)
                .all()
            )
            if len(sizes) == 1:
                stats["linked"] += 1
                logger.info(
                    "%s: offer_id=%s (%s) -> product_size_id=%s (rozmiar=%s)",
                    "LINKUJE" if apply_changes else "DO POWIAZANIA",
                    offer.offer_id,
                    offer.title[:60],
                    sizes[0].id,
                    sizes[0].size,
                )
                if apply_changes:
                    offer.product_size_id = sizes[0].id
            elif len(sizes) == 0:
                stats["no_sizes"] += 1
                logger.info(
                    "BRAK WARIANTOW: offer_id=%s (%s), product_id=%s ma 0 wierszy ProductSize",
                    offer.offer_id,
                    offer.title[:60],
                    offer.product_id,
                )
            else:
                stats["ambiguous"] += 1
                logger.info(
                    "NIEJEDNOZNACZNE: offer_id=%s (%s), product_id=%s ma %s wariantow -> wymaga recznego dowiazania",
                    offer.offer_id,
                    offer.title[:60],
                    offer.product_id,
                    len(sizes),
                )

        if apply_changes:
            db.commit()

    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Faktycznie uzupelnij product_size_id (domyslnie: tylko raport)",
    )
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        stats = backfill(args.apply)

    logger.info("=" * 70)
    logger.info("PODSUMOWANIE")
    logger.info("  Jednoznacznie dowiazane (1 wariant):        %s", stats["linked"])
    logger.info("  Niejednoznaczne (>1 wariantow, pominiete):  %s", stats["ambiguous"])
    logger.info("  Bez wariantow (0 ProductSize, pominiete):   %s", stats["no_sizes"])
    if not args.apply:
        logger.info("  (tryb raportu - uzyj --apply, aby faktycznie zapisac)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
