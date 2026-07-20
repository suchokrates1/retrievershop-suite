"""Export woo_product_id + Allegro image URLs for WP upload."""
from __future__ import annotations

import json

from magazyn.factory import create_app
from magazyn.db import get_session
from magazyn.models.allegro import AllegroOffer
from magazyn.models.products import Product, ProductSize


def main() -> None:
    app = create_app()
    with app.app_context():
        with get_session() as db:
            products = db.query(Product).filter(Product.woo_product_id.isnot(None)).all()
            for product in products:
                best_urls: list[str] = []
                for size in db.query(ProductSize).filter(ProductSize.product_id == product.id):
                    offer = (
                        db.query(AllegroOffer)
                        .filter(
                            AllegroOffer.product_size_id == size.id,
                            AllegroOffer.publication_status == "ACTIVE",
                        )
                        .first()
                    )
                    if not offer or not offer.image_urls:
                        continue
                    try:
                        urls = json.loads(offer.image_urls)
                    except json.JSONDecodeError:
                        continue
                    if len(urls) > len(best_urls):
                        best_urls = urls
                print(f"{product.woo_product_id}\t{product.id}\t{len(best_urls)}\t{'|'.join(best_urls[:8])}")


if __name__ == "__main__":
    main()
