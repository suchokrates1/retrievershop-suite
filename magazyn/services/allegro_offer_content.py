"""Pobieranie i cache opisow/zdjec ofert Allegro."""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from html import escape
from typing import Any, Optional

from ..allegro_api.offers import get_offer_details
from ..db import get_session
from ..models.allegro import AllegroOffer

logger = logging.getLogger(__name__)


def allegro_description_to_html(description: Any) -> str:
    """Zamien sekcje opisu Allegro (sections/items) na prosty HTML."""
    if not description:
        return ""
    if isinstance(description, str):
        return description

    sections = description.get("sections") if isinstance(description, dict) else None
    if not sections:
        return ""

    parts: list[str] = []
    for section in sections:
        items = section.get("items") or []
        for item in items:
            item_type = (item.get("type") or "").upper()
            if item_type == "TEXT":
                content = item.get("content") or ""
                if content:
                    parts.append(content if "<" in content else f"<p>{escape(content)}</p>")
            elif item_type == "IMAGE":
                url = item.get("url")
                if url:
                    parts.append(
                        f'<p><img src="{escape(url)}" alt="{escape("zdjęcie produktu")}" /></p>'
                    )
    return "\n".join(parts)


def extract_image_urls(offer_data: dict) -> list[str]:
    """Wyciagnij URL zdjec z payloadu product-offers."""
    urls: list[str] = []
    images = offer_data.get("images") or []
    for image in images:
        if isinstance(image, str) and image:
            urls.append(image)
        elif isinstance(image, dict):
            url = image.get("url") or image.get("urlOriginal")
            if url:
                urls.append(url)

    # Sekcje opisu tez moga miec obrazki
    description = offer_data.get("description") or {}
    for section in description.get("sections") or []:
        for item in section.get("items") or []:
            if (item.get("type") or "").upper() == "IMAGE":
                url = item.get("url")
                if url and url not in urls:
                    urls.append(url)
    return urls


def sync_offer_content(
    offer_id: str,
    *,
    force: bool = False,
    min_age_hours: int = 24,
) -> bool:
    """Pobierz i zapisz opis/zdjecia dla jednej oferty. Zwraca True gdy zaktualizowano."""
    with get_session() as db:
        offer = db.query(AllegroOffer).filter(AllegroOffer.offer_id == str(offer_id)).first()
        if not offer:
            return False
        if not force and offer.content_synced_at and offer.description_html:
            try:
                synced = datetime.fromisoformat(offer.content_synced_at)
                age_h = (datetime.now(timezone.utc) - synced).total_seconds() / 3600
                if age_h < min_age_hours:
                    return False
            except ValueError:
                pass

        details = get_offer_details(str(offer_id))
        if not details.get("success"):
            logger.warning(
                "Nie udalo sie pobrac tresci oferty %s: %s",
                offer_id,
                details.get("error"),
            )
            return False

        data = details.get("data") or {}
        offer.description_html = allegro_description_to_html(data.get("description"))
        offer.image_urls = json.dumps(extract_image_urls(data), ensure_ascii=False)
        offer.content_synced_at = datetime.now(timezone.utc).isoformat()
        db.commit()
        return True


def sync_linked_offers_content(
    *,
    limit: int = 40,
    force: bool = False,
    sleep_s: float = 0.35,
    include_ended_without_content: bool = True,
) -> dict[str, int]:
    """Batch: tresc dla powiazanych ofert (ACTIVE + ENDED bez cache)."""
    stats = {"updated": 0, "skipped": 0, "errors": 0}
    with get_session() as db:
        from sqlalchemy import or_, and_

        filters = [AllegroOffer.product_size_id.isnot(None)]
        if include_ended_without_content:
            filters.append(
                or_(
                    AllegroOffer.publication_status == "ACTIVE",
                    and_(
                        AllegroOffer.publication_status == "ENDED",
                        or_(
                            AllegroOffer.description_html.is_(None),
                            AllegroOffer.description_html == "",
                            AllegroOffer.content_synced_at.is_(None),
                        ),
                    ),
                )
            )
        else:
            filters.append(AllegroOffer.publication_status == "ACTIVE")
        query = (
            db.query(AllegroOffer)
            .filter(*filters)
            .order_by(AllegroOffer.content_synced_at.asc().nullsfirst())
            .limit(limit)
        )
        offer_ids = [row.offer_id for row in query.all()]

    for offer_id in offer_ids:
        try:
            if sync_offer_content(offer_id, force=force):
                stats["updated"] += 1
            else:
                stats["skipped"] += 1
        except Exception:
            logger.exception("Blad sync tresci oferty %s", offer_id)
            stats["errors"] += 1
        if sleep_s:
            time.sleep(sleep_s)
    return stats


__all__ = [
    "allegro_description_to_html",
    "extract_image_urls",
    "sync_linked_offers_content",
    "sync_offer_content",
]
