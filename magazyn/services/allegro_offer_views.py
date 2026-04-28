"""Konteksty widokow ofert Allegro."""

from __future__ import annotations

import logging
import time
from typing import Callable

import requests
from sqlalchemy import case, or_

from ..allegro_api.core import ALLEGRO_USER_AGENT
from ..allegro_helpers import build_inventory_list
from ..db import get_session
from ..models.allegro import AllegroOffer
from ..models.products import Product, ProductSize
from ..settings_store import settings_store

logger = logging.getLogger(__name__)


def get_ean_for_offer(offer_id: str, *, log: logging.Logger | None = None) -> str:
    """Pobierz EAN oferty z Allegro API."""
    active_logger = log or logger
    try:
        access_token = settings_store.get("ALLEGRO_ACCESS_TOKEN")
        if not access_token:
            return ""

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.allegro.public.v1+json",
            "User-Agent": ALLEGRO_USER_AGENT,
        }
        product_offer = _get_json(f"https://api.allegro.pl/sale/product-offers/{offer_id}", headers)
        product_set = product_offer.get("productSet", [])
        if not product_set:
            return ""

        product_id = product_set[0]["product"]["id"]
        product_data = _get_json(f"https://api.allegro.pl/sale/products/{product_id}", headers)
        for parameter in product_data.get("parameters", []):
            if parameter.get("name") == "EAN (GTIN)":
                values = parameter.get("values", [])
                if values:
                    return values[0]
        return ""
    except Exception as exc:
        active_logger.warning("Error getting EAN for offer %s: %s", offer_id, exc)
        return ""


def build_offers_context(
    *,
    fetch_ean_for_offer: Callable[[str], str] = get_ean_for_offer,
    log: logging.Logger | None = None,
) -> dict:
    """Zbuduj dane do widoku recznego mapowania ofert Allegro."""
    active_logger = log or logger
    with get_session() as db:
        rows = _active_offer_rows(db).all()
        linked_offers: list[dict] = []
        unlinked_offers: list[dict] = []

        for offer, size, product in rows:
            ean = offer.ean or ""
            if not ean and not (offer.product_size_id or offer.product_id):
                ean = _fetch_and_store_ean(db, offer, fetch_ean_for_offer)

            if ean and not offer.product_size_id:
                linked = _link_offer_by_ean(db, offer, ean, active_logger)
                if linked:
                    size, product = linked

            offer_data = _offer_payload(offer, size, product, ean)
            if offer.product_size_id or offer.product_id:
                linked_offers.append(offer_data)
            else:
                unlinked_offers.append(offer_data)

        return {
            "unlinked_offers": unlinked_offers,
            "linked_offers": linked_offers,
            "inventory": build_inventory_list(db),
        }


def build_offers_and_prices_context(
    args,
    *,
    fetch_ean_for_offer: Callable[[str], str] = get_ean_for_offer,
    log: logging.Logger | None = None,
) -> dict:
    """Zbuduj dane do paginowanego widoku ofert i cen Allegro."""
    active_logger = log or logger
    search = args.get("search", "").strip()
    status_filter = args.get("status", "all")
    page = args.get("page", 1, type=int)
    per_page = args.get("per_page", 50, type=int)
    if per_page not in (25, 50, 100):
        per_page = 50
    if page < 1:
        page = 1

    with get_session() as db:
        total_offers = _active_offers_query(db).count()
        matched_offers = _active_offers_query(db).filter(_is_linked_filter()).count()
        query = _filtered_offer_rows(db, search, status_filter)

        total_filtered = query.count()
        total_pages = max(1, (total_filtered + per_page - 1) // per_page)
        if page > total_pages:
            page = total_pages

        rows = query.offset((page - 1) * per_page).limit(per_page).all()
        offers_data = []
        for offer, size, product in rows:
            offer_data = _offer_payload(
                offer,
                size,
                product,
                offer.ean or "",
                include_link_flag=True,
            )
            ean_value = offer.ean or ""
            if not ean_value and not (offer.product_size_id or offer.product_id):
                ean_value = _fetch_and_store_ean(db, offer, fetch_ean_for_offer, active_logger)

            if ean_value and not offer.product_size_id:
                _link_offer_by_ean(db, offer, ean_value, active_logger, source="offers-and-prices")

            offer_data["ean"] = ean_value
            offers_data.append(offer_data)

        return {
            "offers": offers_data,
            "inventory": build_inventory_list(db),
            "total_offers": total_offers,
            "matched_offers": matched_offers,
            "search": search,
            "status_filter": status_filter,
            "page": page,
            "per_page": per_page,
            "total_filtered": total_filtered,
            "total_pages": total_pages,
            "has_prev": page > 1,
            "has_next": page < total_pages,
            "offers_count": len(offers_data),
        }


def new_request_id() -> tuple[float, str]:
    """Zwroc timestamp startu i ID requestu do logow widoku ofert."""
    start_time = time.time()
    return start_time, f"{int(start_time * 1000)}"


def _get_json(url: str, headers: dict) -> dict:
    response = requests.get(url, headers=headers, timeout=10)
    if response.status_code != 200:
        return {}
    return response.json()


def _active_offers_query(db):
    return db.query(AllegroOffer).filter(AllegroOffer.publication_status == "ACTIVE")


def _active_offer_rows(db):
    return _order_offer_rows(_offer_rows_query(db))


def _offer_rows_query(db):
    return (
        db.query(AllegroOffer, ProductSize, Product)
        .filter(AllegroOffer.publication_status == "ACTIVE")
        .outerjoin(ProductSize, AllegroOffer.product_size_id == ProductSize.id)
        .outerjoin(Product, AllegroOffer.product_id == Product.id)
    )


def _order_offer_rows(query):
    return query.order_by(
        case((AllegroOffer.product_size_id.is_(None), 0), else_=1),
        AllegroOffer.title,
    )


def _filtered_offer_rows(db, search: str, status_filter: str):
    query = _offer_rows_query(db)
    if status_filter == "linked":
        query = query.filter(_is_linked_filter())
    elif status_filter == "unlinked":
        query = query.filter(
            AllegroOffer.product_size_id.is_(None),
            AllegroOffer.product_id.is_(None),
        )

    if search:
        search_lower = f"%{search.lower()}%"
        query = query.filter(
            or_(
                AllegroOffer.title.ilike(search_lower),
                AllegroOffer.offer_id.ilike(search_lower),
                AllegroOffer.ean.ilike(search_lower),
                Product.name.ilike(search_lower),
            )
        )
    return _order_offer_rows(query)


def _is_linked_filter():
    return (AllegroOffer.product_size_id.isnot(None)) | (AllegroOffer.product_id.isnot(None))


def _fetch_and_store_ean(db, offer: AllegroOffer, fetch_ean_for_offer, log: logging.Logger | None = None) -> str:
    try:
        ean = fetch_ean_for_offer(offer.offer_id)
        if ean:
            offer.ean = ean
            db.commit()
        return ean
    except Exception as exc:
        if log:
            log.debug("Nie udało się pobrać EAN dla oferty %s: %s", offer.offer_id, exc)
        return ""


def _link_offer_by_ean(
    db,
    offer: AllegroOffer,
    ean: str,
    log: logging.Logger,
    *,
    source: str = "offers",
) -> tuple[ProductSize, Product] | None:
    product_size = db.query(ProductSize).filter(ProductSize.barcode == ean).first()
    if not product_size:
        return None

    offer.product_size_id = product_size.id
    offer.product_id = product_size.product_id
    db.commit()
    suffix = " on offers-and-prices" if source == "offers-and-prices" else ""
    log.info(
        "Linked offer %s to product_size %s by EAN %s%s",
        offer.offer_id,
        product_size.id,
        ean,
        suffix,
    )
    return product_size, product_size.product


def _offer_payload(
    offer: AllegroOffer,
    size: ProductSize | None,
    product: Product | None,
    ean: str,
    *,
    include_link_flag: bool = False,
) -> dict:
    payload = {
        "offer_id": offer.offer_id,
        "title": offer.title,
        "price": offer.price,
        "product_size_id": offer.product_size_id,
        "product_id": offer.product_id,
        "selected_label": _offer_label(product, size),
        "barcode": size.barcode if size else None,
        "ean": ean,
    }
    if include_link_flag:
        payload["is_linked"] = bool(offer.product_size_id or offer.product_id)
    return payload


def _offer_label(product: Product | None, size: ProductSize | None) -> str | None:
    product_for_label = product or (size.product if size else None)
    if product_for_label and size:
        parts = [product_for_label.name]
        if product_for_label.color:
            parts.append(product_for_label.color)
        return " – ".join([" ".join(parts), size.size])
    if product_for_label:
        parts = [product_for_label.name]
        if product_for_label.color:
            parts.append(product_for_label.color)
        return " ".join(parts)
    return None


__all__ = [
    "build_offers_and_prices_context",
    "build_offers_context",
    "get_ean_for_offer",
    "new_request_id",
]