"""Aktualizacja wiersza AllegroOffer przy syncu ofert (tylko gdy cos sie zmienilo)."""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from ..models.allegro import AllegroOffer
from . import allegro_prices

logger = logging.getLogger(__name__)


def upsert_offer_from_api(
    session: Session,
    *,
    offer_id: str,
    title: str,
    price,
    offer_ean: Optional[str],
    publication_status: str,
    product_id: Optional[int],
    product_size_id: Optional[int],
    product_size,
    timestamp_dt: datetime,
) -> AllegroOffer:
    """Zapisz/odswiez oferte. Historia cen i synced_at tylko przy realnej zmianie."""
    timestamp = timestamp_dt.isoformat()
    existing = session.query(AllegroOffer).filter_by(offer_id=offer_id).first()

    if existing is None:
        offer = AllegroOffer(
            offer_id=offer_id,
            title=title,
            price=price,
            ean=offer_ean,
            product_id=product_id,
            product_size_id=product_size_id,
            publication_status=publication_status,
            synced_at=timestamp,
        )
        session.add(offer)
        allegro_prices.record_price_point(
            session,
            offer_id=offer_id,
            product_size_id=product_size_id,
            price=price,
            recorded_at=timestamp_dt,
        )
        return offer

    old_price = Decimal(str(existing.price or 0)).quantize(Decimal("0.01"))
    new_price = Decimal(str(price or 0)).quantize(Decimal("0.01"))
    mapping_may_update = product_size is not None or (
        existing.product_size_id is None and existing.product_id is None
    )
    mapping_changed = False
    if mapping_may_update:
        mapping_changed = (
            existing.product_id != product_id
            or existing.product_size_id != product_size_id
        )
    changed = (
        (existing.title or "") != (title or "")
        or old_price != new_price
        or (existing.ean or None) != (offer_ean or None)
        or (existing.publication_status or "") != (publication_status or "")
        or mapping_changed
    )
    if not changed:
        return existing

    existing.title = title
    existing.price = price
    existing.ean = offer_ean
    existing.publication_status = publication_status
    if mapping_may_update:
        if (
            existing.product_size_id is not None
            and existing.product_size_id != product_size_id
        ):
            logger.warning(
                "Zmiana przypisania oferty %s: pid %s->%s, ps %s->%s (tytul: %s)",
                offer_id,
                existing.product_id,
                product_id,
                existing.product_size_id,
                product_size_id,
                title[:80],
            )
        existing.product_id = product_id
        existing.product_size_id = product_size_id
    existing.synced_at = timestamp
    if old_price != new_price:
        allegro_prices.record_price_point(
            session,
            offer_id=offer_id,
            product_size_id=product_size_id,
            price=price,
            recorded_at=timestamp_dt,
        )
    return existing
