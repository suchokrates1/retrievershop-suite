"""Synchronizacja katalogu magazyn/Allegro → WooCommerce."""

from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import Optional

from ..db import get_session
from ..models.allegro import AllegroOffer
from ..models.products import Product, ProductSize
from ..woocommerce_api import WooClient, WooClientError
from ..woocommerce_api.products import (
    create_or_update_variable_product,
    find_product_by_ean,
    get_product_image_ids,
    upload_product_image_from_url,
    upsert_variation,
)
from .allegro_offer_content import sync_offer_content

logger = logging.getLogger(__name__)


def sync_catalog_to_woo(
    *,
    product_ids: Optional[list[int]] = None,
    limit: int = 200,
    refresh_content: bool = True,
) -> dict[str, int]:
    """Upsert produktow variable + wariantow po EAN do Woo."""
    stats = {"products": 0, "variations": 0, "errors": 0, "skipped": 0}
    try:
        client = WooClient()
    except WooClientError as exc:
        logger.error("Woo catalog sync: %s", exc)
        return {**stats, "errors": 1}

    with get_session() as db:
        q = (
            db.query(Product)
            .join(ProductSize)
            .join(AllegroOffer, AllegroOffer.product_size_id == ProductSize.id)
            .filter(AllegroOffer.publication_status == "ACTIVE")
            .distinct()
        )
        if product_ids:
            q = q.filter(Product.id.in_(product_ids))
        products = q.limit(limit).all()

        for product in products:
            try:
                _sync_one_product(db, client, product, refresh_content=refresh_content, stats=stats)
            except Exception:
                logger.exception("Blad sync produktu id=%s do Woo", product.id)
                stats["errors"] += 1
        db.commit()
    return stats


def _sync_one_product(
    db,
    client: WooClient,
    product: Product,
    *,
    refresh_content: bool,
    stats: dict[str, int],
) -> None:
    sizes = (
        db.query(ProductSize)
        .filter(ProductSize.product_id == product.id)
        .all()
    )
    # Tylko rozmiary z EAN i aktywna oferta
    variants: list[tuple[ProductSize, AllegroOffer]] = []
    for size in sizes:
        offer = (
            db.query(AllegroOffer)
            .filter(
                AllegroOffer.product_size_id == size.id,
                AllegroOffer.publication_status == "ACTIVE",
            )
            .order_by(AllegroOffer.synced_at.desc().nullslast())
            .first()
        )
        if not offer or not size.barcode:
            continue
        variants.append((size, offer))

    if not variants:
        stats["skipped"] += 1
        return

    primary_offer = variants[0][1]
    if refresh_content:
        sync_offer_content(primary_offer.offer_id)
        db.refresh(primary_offer)

    description = primary_offer.description_html or ""
    image_urls = []
    if primary_offer.image_urls:
        try:
            image_urls = json.loads(primary_offer.image_urls)
        except json.JSONDecodeError:
            image_urls = []

    size_options = sorted({size.size for size, _ in variants})
    attributes = [
        {
            "name": "Rozmiar",
            "visible": True,
            "variation": True,
            "options": size_options,
        }
    ]
    name = primary_offer.title or product.name
    # Usun rozmiar z konca tytulu Allegro jesli obecny
    for size_opt in size_options:
        if name.endswith(f" {size_opt}"):
            name = name[: -(len(size_opt) + 1)].rstrip(" -")

    woo_product_id = product.woo_product_id
    if not woo_product_id:
        # Match istniejacego produktu Woo po EAN pierwszego wariantu (bez duplikatow)
        matched = find_product_by_ean(client, variants[0][0].barcode)
        if matched:
            woo_product_id = int(matched["id"])
            product.woo_product_id = woo_product_id
            matched_var = matched.get("_matched_variation")
            if matched_var and not variants[0][0].woo_variation_id:
                variants[0][0].woo_variation_id = int(matched_var["id"])

    # Nie re-uploaduj zdjec gdy produkt Woo juz je ma
    image_ids: list[int] = []
    if woo_product_id:
        image_ids = get_product_image_ids(client, woo_product_id)
    if not image_ids:
        for idx, url in enumerate(image_urls[:8]):
            media_id = upload_product_image_from_url(
                client,
                url,
                filename=f"allegro_{primary_offer.offer_id}_{idx}.jpg",
            )
            if media_id:
                image_ids.append(media_id)

    product_payload = create_or_update_variable_product(
        client,
        woo_product_id=woo_product_id,
        name=name,
        description_html=description,
        image_ids=image_ids,
        image_urls=None if image_ids else image_urls[:8],
        attributes=attributes,
        status="publish",
    )
    woo_product_id = int(product_payload["id"])
    product.woo_product_id = woo_product_id
    stats["products"] += 1

    for size, offer in variants:
        price = str(Decimal(str(offer.price)).quantize(Decimal("0.01")))
        variation = upsert_variation(
            client,
            woo_product_id,
            variation_id=size.woo_variation_id,
            sku=size.barcode,
            regular_price=price,
            stock_quantity=size.quantity or 0,
            size=size.size,
            image_id=None,
        )
        size.woo_variation_id = int(variation["id"])
        stats["variations"] += 1


def push_stock_for_product_size(product_size_id: int) -> bool:
    """Wypchnij stan jednego wariantu do Woo."""
    try:
        client = WooClient()
    except WooClientError:
        return False

    with get_session() as db:
        size = db.query(ProductSize).filter(ProductSize.id == product_size_id).first()
        if not size or not size.woo_variation_id or not size.product or not size.product.woo_product_id:
            return False
        offer = (
            db.query(AllegroOffer)
            .filter(AllegroOffer.product_size_id == size.id)
            .first()
        )
        price = str(offer.price) if offer else "0.00"
        upsert_variation(
            client,
            size.product.woo_product_id,
            variation_id=size.woo_variation_id,
            sku=size.barcode or "",
            regular_price=price,
            stock_quantity=size.quantity or 0,
            size=size.size,
        )
        return True


__all__ = ["push_stock_for_product_size", "sync_catalog_to_woo"]
