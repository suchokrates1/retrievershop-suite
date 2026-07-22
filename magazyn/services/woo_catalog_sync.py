"""Synchronizacja katalogu magazyn/Allegro → WooCommerce (1 parent na rodzine kolorow)."""

from __future__ import annotations

import json
import logging
from collections import defaultdict
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
from .woo_product_naming import (
    apply_woo_lead_to_description,
    build_woo_lead,
    canonical_woo_product_name,
    product_family_key,
    short_description_plain,
)

logger = logging.getLogger(__name__)

VariantRow = tuple[Product, ProductSize, AllegroOffer | None]


def sync_catalog_to_woo(
    *,
    product_ids: Optional[list[int]] = None,
    limit: int = 200,
    refresh_content: bool = True,
) -> dict[str, int]:
    """Upsert produktow variable + wariantow (kolor x rozmiar) po EAN do Woo.

    Grupuje Magazyn Product (1 kolor) w rodziny (category+brand+series) i tworzy
    jeden parent Woo na rodzine.
    """
    stats = {"products": 0, "variations": 0, "errors": 0, "skipped": 0, "families": 0}
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

        families: dict[tuple[str, str, str], list[Product]] = defaultdict(list)
        for product in products:
            families[product_family_key(product)].append(product)

        for key, members in families.items():
            try:
                _sync_one_family(
                    db,
                    client,
                    members,
                    refresh_content=refresh_content,
                    stats=stats,
                )
                stats["families"] += 1
            except Exception:
                logger.exception("Blad sync rodziny %s do Woo", key)
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


def _offer_for_size(db, size: ProductSize) -> AllegroOffer | None:
    offer = (
        db.query(AllegroOffer)
        .filter(
            AllegroOffer.product_size_id == size.id,
            AllegroOffer.publication_status == "ACTIVE",
        )
        .order_by(AllegroOffer.synced_at.desc().nullslast())
        .first()
    )
    if offer:
        return offer
    return (
        db.query(AllegroOffer)
        .filter(AllegroOffer.product_size_id == size.id)
        .order_by(AllegroOffer.synced_at.desc().nullslast())
        .first()
    )


def _collect_family_variants(db, products: list[Product]) -> list[VariantRow]:
    rows: list[VariantRow] = []
    for product in products:
        sizes = (
            db.query(ProductSize)
            .filter(ProductSize.product_id == product.id)
            .all()
        )
        for size in sizes:
            if not size.barcode:
                continue
            offer = _offer_for_size(db, size)
            if offer or size.quantity > 0 or size.woo_variation_id or product.woo_product_id:
                rows.append((product, size, offer))
    return rows


def _pick_primary_offer(variants: list[VariantRow]) -> AllegroOffer | None:
    """Najbogatszy ACTIVE (desc+zdjecia), inaczej dowolny z trescia."""
    best: AllegroOffer | None = None
    best_score = -1
    for _, _, offer in variants:
        if offer is None:
            continue
        desc_len = len((offer.description_html or "").strip())
        try:
            imgs = json.loads(offer.image_urls or "[]")
        except json.JSONDecodeError:
            imgs = []
        score = desc_len + 50 * len(imgs)
        if (offer.publication_status or "").upper() == "ACTIVE":
            score += 10_000
        if score > best_score:
            best_score = score
            best = offer
    return best


def _merge_image_urls(variants: list[VariantRow], primary: AllegroOffer | None) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()

    def _add_from(offer: AllegroOffer | None) -> None:
        if not offer or not offer.image_urls:
            return
        try:
            items = json.loads(offer.image_urls)
        except json.JSONDecodeError:
            return
        for url in items:
            u = (url or "").strip()
            if u and u not in seen:
                seen.add(u)
                urls.append(u)

    _add_from(primary)
    for _, _, offer in variants:
        if offer is not primary:
            _add_from(offer)
        if len(urls) >= 16:
            break
    return urls


def _elect_shared_parent_id(
    products: list[Product],
    variants: list[VariantRow],
) -> Optional[int]:
    """Wybierz wspolne woo_product_id: najczestsze sposrod siblingow, inaczej pierwsze EAN."""
    counts: dict[int, int] = defaultdict(int)
    for product in products:
        if product.woo_product_id:
            counts[int(product.woo_product_id)] += 1
    if counts:
        return max(counts.items(), key=lambda kv: (kv[1], kv[0]))[0]
    return None


def _sync_one_family(
    db,
    client: WooClient,
    products: list[Product],
    *,
    refresh_content: bool,
    stats: dict[str, int],
) -> None:
    if not products:
        stats["skipped"] += 1
        return

    variants = _collect_family_variants(db, products)
    if not variants:
        stats["skipped"] += 1
        return

    primary_offer = _pick_primary_offer(variants)
    if primary_offer:
        if refresh_content:
            sync_offer_content(primary_offer.offer_id)
            db.refresh(primary_offer)
        _ensure_offer_content(db, primary_offer)

    description = (primary_offer.description_html if primary_offer else None) or ""
    image_urls = _merge_image_urls(variants, primary_offer)

    colors = sorted(
        {
            (p.color or "").strip()
            for p, _, _ in variants
            if (p.color or "").strip()
        }
    )
    size_options = sorted({(s.size or "").strip() for _, s, _ in variants if (s.size or "").strip()})
    seed = products[0]
    attributes = build_product_attributes(
        client,
        brand=seed.brand,
        series=seed.series,
        colors=colors,
        size_options=size_options,
    )
    name = canonical_woo_product_name(seed)
    lead = build_woo_lead(
        seed,
        description,
        colors=colors,
        sizes=size_options,
    )
    description = apply_woo_lead_to_description(description, lead)
    short_desc = lead if lead else (
        short_description_plain(description) if description else None
    )

    woo_product_id = _elect_shared_parent_id(products, variants)
    if not woo_product_id:
        matched = find_product_by_ean(client, variants[0][1].barcode)
        if matched:
            woo_product_id = int(matched["id"])
            matched_var = matched.get("_matched_variation")
            if matched_var and not variants[0][1].woo_variation_id:
                variants[0][1].woo_variation_id = int(matched_var["id"])

    # Resolve against first product; then apply to all siblings
    woo_product_id = _resolve_variable_parent_id(client, seed, woo_product_id)

    category_ids: list[int] = []
    cat_id = ensure_product_category(client, seed.category)
    if cat_id:
        category_ids.append(cat_id)

    image_ids = _collect_image_ids(
        client,
        woo_product_id=woo_product_id,
        image_urls=image_urls,
        offer_id=primary_offer.offer_id if primary_offer else None,
        product_id=int(seed.id),
        alt_text=name,
    )

    product_payload = create_or_update_variable_product(
        client,
        woo_product_id=woo_product_id,
        name=name,
        description_html=description,
        short_description=short_desc,
        image_ids=image_ids,
        image_urls=None if image_ids else image_urls[:8],
        attributes=attributes,
        category_ids=category_ids or None,
        status="publish",
    )
    woo_product_id = int(product_payload["id"])
    for product in products:
        product.woo_product_id = woo_product_id
    stats["products"] += 1

    for product, size, offer in variants:
        price_src = offer.price if offer is not None else "0.00"
        price = str(Decimal(str(price_src)).quantize(Decimal("0.01")))
        color = (product.color or "").strip() or None
        variation = upsert_variation(
            client,
            woo_product_id,
            variation_id=size.woo_variation_id,
            sku=size.barcode,
            regular_price=price,
            stock_quantity=size.quantity or 0,
            size=size.size,
            color=color,
            image_id=None,
        )
        size.woo_variation_id = int(variation["id"])
        stats["variations"] += 1
        # Stock juz w upsert_variation — bez osobnego maybe_push (osobna sesja
        # moglaby czytac stare woo_product_id przed commit).


def _sync_one_product(
    db,
    client: WooClient,
    product: Product,
    *,
    refresh_content: bool,
    stats: dict[str, int],
) -> None:
    """Kompatybilnosc: sync pojedynczego produktu = sync jego rodziny (1 czlonek)."""
    _sync_one_family(
        db,
        client,
        [product],
        refresh_content=refresh_content,
        stats=stats,
    )


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
            logger.info(
                "Woo product %s: variation %s -> parent %s",
                product.id,
                woo_product_id,
                parent_id,
            )
            return parent_id
        product.woo_product_id = None
        return None
    logger.warning(
        "Woo product %s id=%s type=%s — tworze nowy variable",
        product.id,
        woo_product_id,
        ptype,
    )
    product.woo_product_id = None
    return None


__all__ = [
    "sync_catalog_to_woo",
]
