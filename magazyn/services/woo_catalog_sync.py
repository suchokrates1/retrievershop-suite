"""Synchronizacja katalogu magazyn/Allegro → WooCommerce."""

from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import Optional

from sqlalchemy import or_

from ..db import get_session
from ..models.allegro import AllegroOffer
from ..models.products import Product, ProductSize
from ..woocommerce_api import WooClient, WooClientError
from ..woocommerce_api.attributes import build_product_attributes
from ..woocommerce_api.categories import ensure_product_category
from ..woocommerce_api.products import (
    create_or_update_variable_product,
    find_product_by_ean,
    get_product_image_ids,
    upload_product_image_from_url,
    upsert_variation,
)
from .allegro_offer_content import sync_offer_content
from .woo_product_naming import canonical_woo_product_name, short_description_plain

logger = logging.getLogger(__name__)


def sync_catalog_to_woo(
    *,
    product_ids: Optional[list[int]] = None,
    limit: int = 200,
    refresh_content: bool = True,
) -> dict[str, int]:
    """Upsert produktow variable + wariantow po EAN do Woo.

    Bierze produkty z barcode oraz (ACTIVE Allegro LUB stock>0 LUB juz zmapowane).
    """
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
            .outerjoin(AllegroOffer, AllegroOffer.product_size_id == ProductSize.id)
            .filter(
                ProductSize.barcode.isnot(None),
                ProductSize.barcode != "",
                or_(
                    AllegroOffer.publication_status == "ACTIVE",
                    ProductSize.quantity > 0,
                    Product.woo_product_id.isnot(None),
                ),
            )
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


def _ensure_offer_content(db, offer: AllegroOffer, *, force: bool = False) -> None:
    """Dociagnij opis/zdjecia gdy cache pusty (takze ENDED)."""
    needs = force or not (offer.description_html or "").strip()
    if not needs:
        try:
            imgs = json.loads(offer.image_urls or "[]")
            needs = not imgs
        except json.JSONDecodeError:
            needs = True
    if not needs:
        return
    sync_offer_content(offer.offer_id, force=True)
    db.refresh(offer)


def _collect_image_ids(
    client: WooClient,
    *,
    woo_product_id: Optional[int],
    image_urls: list[str],
    offer_id: Optional[str],
    product_id: int,
    alt_text: str,
) -> list[int]:
    """Istniejace ID + dograj brakujace z Allegro (max 8)."""
    image_ids: list[int] = []
    if woo_product_id:
        image_ids = get_product_image_ids(client, woo_product_id)
    target = 8
    if len(image_ids) >= target or not image_urls:
        return image_ids[:target]
    start_idx = len(image_ids)
    for idx, url in enumerate(image_urls[start_idx:target], start=start_idx):
        filename = (
            f"allegro_{offer_id}_{idx}.jpg" if offer_id else f"mag_{product_id}_{idx}.jpg"
        )
        media_id = upload_product_image_from_url(
            client, url, filename=filename, alt_text=alt_text
        )
        if media_id and int(media_id) not in image_ids:
            image_ids.append(int(media_id))
    return image_ids


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
    variants: list[tuple[ProductSize, AllegroOffer | None]] = []
    for size in sizes:
        if not size.barcode:
            continue
        offer = (
            db.query(AllegroOffer)
            .filter(
                AllegroOffer.product_size_id == size.id,
                AllegroOffer.publication_status == "ACTIVE",
            )
            .order_by(AllegroOffer.synced_at.desc().nullslast())
            .first()
        )
        if not offer:
            offer = (
                db.query(AllegroOffer)
                .filter(AllegroOffer.product_size_id == size.id)
                .order_by(AllegroOffer.synced_at.desc().nullslast())
                .first()
            )
        if offer or size.quantity > 0 or size.woo_variation_id or product.woo_product_id:
            variants.append((size, offer))

    if not variants:
        stats["skipped"] += 1
        return

    primary_offer = next((o for _, o in variants if o is not None), None)
    if primary_offer:
        if refresh_content:
            sync_offer_content(primary_offer.offer_id)
            db.refresh(primary_offer)
        _ensure_offer_content(db, primary_offer)

    description = (primary_offer.description_html if primary_offer else None) or ""
    image_urls: list[str] = []
    if primary_offer and primary_offer.image_urls:
        try:
            image_urls = json.loads(primary_offer.image_urls)
        except json.JSONDecodeError:
            image_urls = []

    size_options = sorted({size.size for size, _ in variants})
    attributes = build_product_attributes(
        client,
        brand=product.brand,
        series=product.series,
        color=product.color,
        size_options=size_options,
    )
    name = canonical_woo_product_name(product)

    woo_product_id = product.woo_product_id
    if not woo_product_id:
        matched = find_product_by_ean(client, variants[0][0].barcode)
        if matched:
            woo_product_id = int(matched["id"])
            product.woo_product_id = woo_product_id
            matched_var = matched.get("_matched_variation")
            if matched_var and not variants[0][0].woo_variation_id:
                variants[0][0].woo_variation_id = int(matched_var["id"])

    woo_product_id = _resolve_variable_parent_id(client, product, woo_product_id)

    category_ids: list[int] = []
    cat_id = ensure_product_category(client, product.category)
    if cat_id:
        category_ids.append(cat_id)

    image_ids = _collect_image_ids(
        client,
        woo_product_id=woo_product_id,
        image_urls=image_urls,
        offer_id=primary_offer.offer_id if primary_offer else None,
        product_id=int(product.id),
        alt_text=name,
    )

    product_payload = create_or_update_variable_product(
        client,
        woo_product_id=woo_product_id,
        name=name,
        description_html=description,
        short_description=short_description_plain(description) if description else None,
        image_ids=image_ids,
        image_urls=None if image_ids else image_urls[:8],
        attributes=attributes,
        category_ids=category_ids or None,
        status="publish",
    )
    woo_product_id = int(product_payload["id"])
    product.woo_product_id = woo_product_id
    stats["products"] += 1

    for size, offer in variants:
        price_src = offer.price if offer is not None else "0.00"
        price = str(Decimal(str(price_src)).quantize(Decimal("0.01")))
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

    for size in sizes:
        if size.woo_variation_id and size.barcode:
            maybe_push_woo_stock(size.id, quantity=int(size.quantity or 0))


def _resolve_variable_parent_id(
    client: WooClient,
    product: Product,
    woo_product_id: Optional[int],
) -> Optional[int]:
    """Jesli zapisane ID to variation, przepnij na parent variable (albo wyczysc)."""
    if not woo_product_id:
        return None
    try:
        existing = client.get(f"wp-json/wc/v3/products/{woo_product_id}")
    except WooClientError as exc:
        if exc.status_code == 404:
            product.woo_product_id = None
            return None
        raise
    if not existing:
        product.woo_product_id = None
        return None

    ptype = (existing.get("type") or "").lower()
    if ptype == "variable":
        return int(existing["id"])
    if ptype == "variation":
        parent_id = existing.get("parent_id") or existing.get("parent")
        if parent_id:
            parent_id = int(parent_id)
            product.woo_product_id = parent_id
            var_id = int(existing["id"])
            var_sku = (existing.get("sku") or "").strip()
            for size in product.sizes or []:
                if var_sku and (size.barcode or "").strip() == var_sku:
                    size.woo_variation_id = var_id
                    break
            # Bez trafienia po EAN nie przypisuj variation do pierwszego pustego
            # rozmiaru — to tworzylo duplikaty mapowan (np. XS bez barcode).
            logger.info(
                "Woo product %s: variation %s -> parent %s",
                product.id,
                woo_product_id,
                parent_id,
            )
            return parent_id
        product.woo_product_id = None
        return None
    # simple / inne — utworzymy nowy variable przy upsert bez id
    logger.warning(
        "Woo product %s id=%s type=%s — tworze nowy variable",
        product.id,
        woo_product_id,
        ptype,
    )
    product.woo_product_id = None
    return None


def push_stock_for_product_size(
    product_size_id: int,
    *,
    quantity: Optional[int] = None,
) -> bool:
    """Wypchnij stan jednego wariantu do Woo.

    ``quantity`` — opcjonalnie podaj jawnie (np. przed commit sesji zrodlowej),
    inaczej odczyt z DB.
    """
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
        stock_qty = int(size.quantity or 0) if quantity is None else max(0, int(quantity))
        upsert_variation(
            client,
            size.product.woo_product_id,
            variation_id=size.woo_variation_id,
            sku=size.barcode or "",
            regular_price=price,
            stock_quantity=stock_qty,
            size=size.size,
        )
        return True


def maybe_push_woo_stock(product_size_id: int | None, *, quantity: Optional[int] = None) -> None:
    """Best-effort push stanu do Woo; nigdy nie rzuca do callera."""
    if not product_size_id:
        return
    try:
        push_stock_for_product_size(int(product_size_id), quantity=quantity)
    except Exception:
        logger.exception("Nie zaktualizowano stanu Woo dla product_size_id=%s", product_size_id)


__all__ = ["maybe_push_woo_stock", "push_stock_for_product_size", "sync_catalog_to_woo"]
