#!/usr/bin/env python3
"""Rozdziel wspoldzielone woo_product_id: 1 kolor magazynu = 1 parent Woo.

Po merge kolorow (stary model) wiele Product mialo ten sam woo_product_id.
Ten skrypt:
  - zostawia 1 kolor na istniejącym Woo parentcie (keeper),
  - pozostale kolory odlacza (czysci SKU wariantow + mapowania),
  - syncuje kazdy kolor osobno → nowe Woo ID,
  - aktualizuje keepera (nazwa z kolorem, atrybuty).

Domyslnie dry-run. Apply: --apply
Pilot: --woo-id 3440  albo  --product-ids 56,73

  DISABLE_SCHEDULERS=1 PYTHONPATH=/app python scripts/ops/woo_split_color_products.py --all
  DISABLE_SCHEDULERS=1 PYTHONPATH=/app python scripts/ops/woo_split_color_products.py --all --apply
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from typing import Any, Optional

os.environ["DISABLE_SCHEDULERS"] = "1"

from magazyn.db import get_session
from magazyn.factory import create_app
from magazyn.models.products import Product, ProductSize
from magazyn.services.woo_catalog_sync import _sync_one_family
from magazyn.services.woo_product_naming import canonical_woo_product_name, product_family_key
from magazyn.woocommerce_api import WooClient, WooClientError


def _mapped_variation_count(db, product: Product) -> int:
    return (
        db.query(ProductSize)
        .filter(
            ProductSize.product_id == product.id,
            ProductSize.woo_variation_id.isnot(None),
        )
        .count()
    )


def _elect_keeper(db, products: list[Product]) -> Product:
    scored = sorted(
        products,
        key=lambda p: (-_mapped_variation_count(db, p), int(p.id or 0)),
    )
    return scored[0]


def _clear_variation_sku(client: WooClient, parent_id: int, variation_id: int) -> dict[str, Any]:
    try:
        client.put(
            f"wp-json/wc/v3/products/{parent_id}/variations/{variation_id}",
            json={"sku": "", "status": "private"},
        )
        return {"cleared_sku": variation_id, "parent": parent_id}
    except WooClientError as exc:
        return {"clear_sku_error": variation_id, "parent": parent_id, "error": str(exc)}


def _detach_product(
    db,
    client: WooClient,
    product: Product,
    shared_woo_id: int,
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    sizes = db.query(ProductSize).filter(ProductSize.product_id == product.id).all()
    for size in sizes:
        if not size.woo_variation_id:
            continue
        var_id = int(size.woo_variation_id)
        actions.append(_clear_variation_sku(client, shared_woo_id, var_id))
        size.woo_variation_id = None
        actions.append({"cleared_mapping": size.id, "ean": size.barcode})
    product.woo_product_id = None
    actions.append({"cleared_woo_product_id": product.id, "was": shared_woo_id})
    return actions


def _split_group(
    db,
    client: WooClient,
    woo_id: int,
    products: list[Product],
    *,
    apply: bool,
) -> dict[str, Any]:
    keeper = _elect_keeper(db, products)
    others = [p for p in products if p.id != keeper.id]
    result: dict[str, Any] = {
        "woo_id": woo_id,
        "keeper_id": keeper.id,
        "keeper_color": keeper.color,
        "other_ids": [p.id for p in others],
        "other_colors": [p.color for p in others],
        "families": ["|".join(product_family_key(p)) for p in products],
        "applied": False,
    }
    if not others:
        result["skipped"] = "single_member"
        return result

    if not apply:
        result["would_rename_keeper"] = canonical_woo_product_name(keeper)
        result["would_create_for"] = [
            {"id": p.id, "color": p.color, "name": canonical_woo_product_name(p)}
            for p in others
        ]
        return result

    detach_actions: list[dict[str, Any]] = []
    for other in others:
        detach_actions.extend(_detach_product(db, client, other, woo_id))
    result["detach"] = detach_actions
    db.flush()

    stats_all: list[dict[str, int]] = []
    created: list[dict[str, Any]] = []
    for other in others:
        stats = {"products": 0, "variations": 0, "errors": 0, "skipped": 0}
        _sync_one_family(db, client, [other], refresh_content=False, stats=stats)
        db.flush()
        stats_all.append(stats)
        created.append(
            {
                "product_id": other.id,
                "color": other.color,
                "woo_product_id": other.woo_product_id,
                "name": canonical_woo_product_name(other),
                "stats": stats,
            }
        )

    keeper_stats = {"products": 0, "variations": 0, "errors": 0, "skipped": 0}
    _sync_one_family(db, client, [keeper], refresh_content=False, stats=keeper_stats)
    db.flush()

    result["created"] = created
    result["keeper_woo_product_id"] = keeper.woo_product_id
    result["keeper_name"] = canonical_woo_product_name(keeper)
    result["keeper_stats"] = keeper_stats
    result["applied"] = True
    return result


def _load_shared_groups(
    db,
    *,
    woo_id: Optional[int] = None,
    product_ids: Optional[set[int]] = None,
) -> dict[int, list[Product]]:
    by_woo: dict[int, list[Product]] = defaultdict(list)
    q = db.query(Product).filter(Product.woo_product_id.isnot(None))
    if product_ids:
        # Zaladuj cale grupy wspoldzielace ID z wybranymi produktami
        seed = q.filter(Product.id.in_(product_ids)).all()
        seed_wids = {int(p.woo_product_id) for p in seed if p.woo_product_id}
        if not seed_wids:
            return {}
        q = db.query(Product).filter(Product.woo_product_id.in_(seed_wids))
    for p in q.all():
        by_woo[int(p.woo_product_id)].append(p)
    shared = {wid: ps for wid, ps in by_woo.items() if len(ps) > 1}
    if woo_id is not None:
        shared = {wid: ps for wid, ps in shared.items() if wid == woo_id}
    return dict(sorted(shared.items(), key=lambda kv: -len(kv[1])))


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true", help="Wszystkie wspoldzielone woo_product_id")
    parser.add_argument("--woo-id", type=int, help="Tylko jedno Woo ID (np. 3440 Blossom)")
    parser.add_argument(
        "--product-ids",
        help="CSV id produktow magazynu — rozdziel ich wspoldzielone grupy",
    )
    parser.add_argument("--apply", action="store_true", help="Wykonaj zmiany (domyslnie dry-run)")
    args = parser.parse_args(argv)

    if not args.all and args.woo_id is None and not args.product_ids:
        parser.error("podaj --all, --woo-id albo --product-ids")

    product_ids = None
    if args.product_ids:
        product_ids = {int(x.strip()) for x in args.product_ids.split(",") if x.strip()}

    app = create_app()
    results: list[dict[str, Any]] = []
    with app.app_context():
        client = WooClient()
        with get_session() as db:
            groups = _load_shared_groups(db, woo_id=args.woo_id, product_ids=product_ids)
            print(f"shared_groups={len(groups)} mode={'APPLY' if args.apply else 'DRY-RUN'}")
            for wid, products in groups.items():
                colors = ", ".join(sorted({(p.color or "?") for p in products}))
                print(f"group woo={wid} n={len(products)} colors=[{colors}] ids={[p.id for p in products]}")
                res = _split_group(db, client, wid, products, apply=args.apply)
                results.append(res)
                print(json.dumps(res, ensure_ascii=False, default=str))
            if args.apply:
                db.commit()
            else:
                db.rollback()

    shared_after = 0
    if args.apply:
        with app.app_context():
            with get_session() as db:
                shared_after = len(_load_shared_groups(db))
        print(f"shared_groups_after={shared_after}")

    print(f"done groups={len(results)} apply={args.apply}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
