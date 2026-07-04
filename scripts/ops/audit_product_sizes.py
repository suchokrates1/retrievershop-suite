#!/usr/bin/env python3
"""Audyt i czyszczenie "widmowych" wierszy ProductSize.

Kontekst: create_product()/update_product() (magazyn/domain/products.py)
tworzyly historycznie wiersz ProductSize dla KAZDEGO rozmiaru z ALL_SIZES
(XS, S, M, L, XL, 2XL, 3XL, Uniwersalny) niezaleznie od tego, czy produkt
tego rozmiaru w ogole uzywa. W efekcie prawie kazdy produkt ma dodatkowe
puste wiersze (quantity=0, barcode=NULL), co lamie zasade "produkt albo ma
rozmiary XS-3XL, albo tylko Uniwersalny - nigdy oba" i zasmieca liste
dopasowan ofert Allegro.

Ten skrypt klasyfikuje KAZDY produkt na podstawie tego, ktore jego wiersze
ProductSize sa "aktywne" (quantity != 0 OR barcode IS NOT NULL):

    Typ A (single-SKU):  aktywny tylko rozmiar "Uniwersalny"
                         -> pozostale (nieaktywne) wiersze XS-3XL to widma
    Typ B (rozmiarowy):  aktywne tylko rozmiary XS-3XL
                         -> nieaktywny wiersz "Uniwersalny" to widmo
    Typ C (KONFLIKT):    aktywny i "Uniwersalny" i inny rozmiar jednoczesnie
                         -> NIGDY nie usuwamy automatycznie, tylko raport
    Typ D (pusty):       zaden wiersz nie jest aktywny -> nic do zrobienia

Przed usunieciem KAZDEGO "widmowego" wiersza skrypt sprawdza, czy nie jest
przywolywany gdziekolwiek indziej (AllegroOffer, AllegroPriceHistory,
OrderProduct, StocktakeItem po FK, Sale/PurchaseBatch po product_id+size).
Jesli tak - wiersz NIE jest usuwany, tylko oznaczony jako wyjatek.

Domyslnie (bez --apply) skrypt tylko raportuje - zero zapisow do bazy.
Uzycie:
    python scripts/ops/audit_product_sizes.py
    python scripts/ops/audit_product_sizes.py --apply
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from magazyn.constants import ALL_SIZES
from magazyn.db import get_session
from magazyn.factory import create_app
from magazyn.models.allegro import AllegroOffer, AllegroPriceHistory
from magazyn.models.orders import OrderProduct
from magazyn.models.products import Product, ProductSize, PurchaseBatch, Sale
from magazyn.models.stocktakes import StocktakeItem

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("audit_product_sizes")

UNIWERSALNY = "Uniwersalny"


def _is_active(ps: ProductSize) -> bool:
    return bool(ps.quantity) or bool(ps.barcode)


def _has_external_references(db, ps: ProductSize) -> list[str]:
    """Zwroc liste powodow, dla ktorych wiersza NIE wolno usunac."""
    reasons: list[str] = []

    if db.query(AllegroOffer).filter_by(product_size_id=ps.id).first():
        reasons.append("AllegroOffer.product_size_id")
    if db.query(AllegroPriceHistory).filter_by(product_size_id=ps.id).first():
        reasons.append("AllegroPriceHistory.product_size_id")
    if db.query(OrderProduct).filter_by(product_size_id=ps.id).first():
        reasons.append("OrderProduct.product_size_id")
    if db.query(StocktakeItem).filter_by(product_size_id=ps.id).first():
        reasons.append("StocktakeItem.product_size_id")
    if (
        db.query(PurchaseBatch)
        .filter_by(product_id=ps.product_id, size=ps.size)
        .first()
    ):
        reasons.append("PurchaseBatch(product_id,size)")
    if db.query(Sale).filter_by(product_id=ps.product_id, size=ps.size).first():
        reasons.append("Sale(product_id,size)")

    return reasons


def _product_label(product: Product) -> str:
    parts = [product.category or "?"]
    if product.brand:
        parts.append(product.brand)
    if product.series:
        parts.append(product.series)
    if product.color:
        parts.append(product.color)
    return " / ".join(parts) + f" (id={product.id})"


def audit(apply_changes: bool) -> dict[str, int]:
    stats = {
        "type_a": 0,
        "type_b": 0,
        "type_c": 0,
        "type_d": 0,
        "phantom_candidates": 0,
        "deleted": 0,
        "skipped_has_history": 0,
    }

    with get_session() as db:
        products = db.query(Product).order_by(Product.id).all()

        for product in products:
            sizes = list(product.sizes)
            uniwersalny_rows = [s for s in sizes if s.size == UNIWERSALNY]
            other_rows = [s for s in sizes if s.size != UNIWERSALNY]

            active_uniwersalny = any(_is_active(s) for s in uniwersalny_rows)
            active_other = any(_is_active(s) for s in other_rows)

            if active_uniwersalny and active_other:
                stats["type_c"] += 1
                logger.info("=" * 70)
                logger.info("TYP C - KONFLIKT: %s", _product_label(product))
                for s in sizes:
                    if _is_active(s):
                        logger.info(
                            "    aktywny: rozmiar=%-12s qty=%-4s barcode=%s",
                            s.size,
                            s.quantity,
                            s.barcode or "-",
                        )
                logger.info("    -> WYMAGA RECZNEJ DECYZJI, pomijam (nie usuwam nic)")
                continue

            if active_uniwersalny and not active_other:
                stats["type_a"] += 1
                candidates = [s for s in other_rows if not _is_active(s)]
            elif active_other and not active_uniwersalny:
                stats["type_b"] += 1
                candidates = [s for s in uniwersalny_rows if not _is_active(s)]
            else:
                stats["type_d"] += 1
                continue

            for ps in candidates:
                stats["phantom_candidates"] += 1
                reasons = _has_external_references(db, ps)
                if reasons:
                    stats["skipped_has_history"] += 1
                    logger.info(
                        "WYJATEK (ma historie, NIE usuwam): product=%s rozmiar=%s "
                        "ps_id=%s -> %s",
                        _product_label(product),
                        ps.size,
                        ps.id,
                        ", ".join(reasons),
                    )
                    continue

                logger.info(
                    "%s: product=%s rozmiar=%s ps_id=%s (qty=%s, barcode=%s)",
                    "USUWAM" if apply_changes else "DO USUNIECIA",
                    _product_label(product),
                    ps.size,
                    ps.id,
                    ps.quantity,
                    ps.barcode or "-",
                )
                if apply_changes:
                    db.delete(ps)
                    stats["deleted"] += 1

        if apply_changes:
            db.commit()

    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Faktycznie usun bezpieczne widmowe wiersze (domyslnie: tylko raport)",
    )
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        stats = audit(args.apply)

    logger.info("=" * 70)
    logger.info("PODSUMOWANIE (ALL_SIZES=%s)", ALL_SIZES)
    logger.info("  Typ A (single-SKU, tylko Uniwersalny aktywny): %s", stats["type_a"])
    logger.info("  Typ B (rozmiarowy, Uniwersalny nieaktywny):    %s", stats["type_b"])
    logger.info("  Typ C (KONFLIKT - wymaga recznej decyzji):    %s", stats["type_c"])
    logger.info("  Typ D (produkt bez zadnych aktywnych danych): %s", stats["type_d"])
    logger.info("  Kandydaci na widmowe wiersze:                 %s", stats["phantom_candidates"])
    logger.info("  Pominiete (maja historie w innych tabelach):  %s", stats["skipped_has_history"])
    if args.apply:
        logger.info("  Usuniete:                                     %s", stats["deleted"])
    else:
        logger.info("  (tryb raportu - uzyj --apply, aby faktycznie usunac)")

    return 1 if stats["type_c"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
