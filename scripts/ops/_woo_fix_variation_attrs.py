#!/usr/bin/env python3
"""Napraw atrybuty wariantow na juz scalonym parentcie (Kolor+Rozmiar po ID)."""
from __future__ import annotations

import os
import sys

os.environ.setdefault("DISABLE_SCHEDULERS", "1")

from magazyn.db import get_session
from magazyn.factory import create_app
from magazyn.models.products import Product, ProductSize
from magazyn.services.woo_product_naming import product_family_key
from magazyn.woocommerce_api import WooClient
from magazyn.woocommerce_api.attributes import ensure_attribute
from magazyn.woocommerce_api.products import upsert_variation
from magazyn.models.allegro import AllegroOffer

FAMILY = tuple(p.strip().lower() for p in (sys.argv[1] if len(sys.argv) > 1 else "szelki|truelove|front line premium").split("|"))


def main() -> None:
    app = create_app()
    with app.app_context():
        client = WooClient()
        color_id = ensure_attribute(client, "Kolor")
        size_id = ensure_attribute(client, "Rozmiar")
        print(f"color_id={color_id} size_id={size_id}")
        with get_session() as db:
            products = [p for p in db.query(Product).all() if product_family_key(p) == FAMILY]
            if not products:
                print("no products")
                return
            parent_id = products[0].woo_product_id
            print(f"parent={parent_id} members={len(products)}")
            ok = 0
            for product in products:
                sizes = db.query(ProductSize).filter(ProductSize.product_id == product.id).all()
                for size in sizes:
                    if not size.barcode or not size.woo_variation_id:
                        continue
                    offer = (
                        db.query(AllegroOffer)
                        .filter(AllegroOffer.product_size_id == size.id)
                        .first()
                    )
                    price = str(offer.price) if offer else "0.00"
                    color = (product.color or "").strip() or None
                    upsert_variation(
                        client,
                        int(parent_id),
                        variation_id=int(size.woo_variation_id),
                        sku=size.barcode,
                        regular_price=price,
                        stock_quantity=int(size.quantity or 0),
                        size=size.size,
                        color=color,
                    )
                    ok += 1
                    print(f"fixed var={size.woo_variation_id} sku={size.barcode} color={color} size={size.size}")
            db.commit()
            print(f"done fixed={ok}")
            # verify sample
            vars_ = client.get(
                f"wp-json/wc/v3/products/{parent_id}/variations",
                params={"per_page": 3},
            ) or []
            for v in vars_:
                print("sample", v.get("id"), v.get("sku"), v.get("attributes"))


if __name__ == "__main__":
    main()
