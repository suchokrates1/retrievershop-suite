"""Oferta katalogowa produktu: tytul, opis i zdjecia do wysylki na marketplace."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import or_

from ..db import get_session
from ..domain.offer_templates import offer_title, render_offer_html, template_for
from ..models.allegro import AllegroOffer
from ..models.products import Product, ProductOffer, ProductSize

_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")
_EMPTY_DESCRIPTIONS = {"", "<!-- allegro-404 -->"}


def parse_image_urls(raw: str | None) -> list[str]:
    if not raw:
        return []
    text = raw.strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            loaded = json.loads(text)
        except json.JSONDecodeError:
            loaded = None
        if isinstance(loaded, list):
            return [str(url).strip() for url in loaded if str(url).strip()]
    return [line.strip() for line in text.splitlines() if line.strip()]


def dump_image_urls(urls: list[str]) -> str:
    cleaned = []
    for url in urls:
        value = url.strip()
        if value and value not in cleaned:
            cleaned.append(value)
    return json.dumps(cleaned, ensure_ascii=False)


def public_image_urls(urls: list[str]) -> list[str]:
    return [url for url in urls if url.startswith("https://") or url.startswith("http://")]


def description_is_usable(html: str | None) -> bool:
    return (html or "").strip() not in _EMPTY_DESCRIPTIONS


def html_to_text(html: str | None) -> str:
    text = _TAG_RE.sub(" ", html or "")
    return _SPACE_RE.sub(" ", text).strip()


def offer_view(offer: ProductOffer | None) -> dict[str, Any]:
    images = public_image_urls(parse_image_urls(offer.image_urls if offer else None))
    description = offer.description_html if offer and description_is_usable(offer.description_html) else ""
    title = (offer.title or "").strip() if offer else ""
    return {
        "id": offer.id if offer else None,
        "title": title,
        "description_html": (offer.description_html or "") if offer else "",
        "description_text": html_to_text(description),
        "image_urls": images,
        "image_lines": "\n".join(images),
        "source": offer.source if offer else None,
        "allegro_offer_id": offer.allegro_offer_id if offer else None,
        "updated_at": offer.updated_at if offer else None,
        "has_title": bool(title),
        "has_description": bool(description),
        "has_images": bool(images),
        "ready": bool(title and description and images),
    }


def list_catalog_offers(search: str = "") -> list[dict[str, Any]]:
    needle = search.strip().lower()
    with get_session() as db:
        products = db.query(Product).order_by(Product.id).all()
        offers = {row.product_id: row for row in db.query(ProductOffer).all()}
        rows = []
        for product in products:
            view = offer_view(offers.get(product.id))
            label = product.display_name
            if needle and needle not in label.lower() and needle not in view["title"].lower():
                continue
            rows.append({"product_id": product.id, "product_name": label, **view})
        return rows


def get_catalog_offer(product_id: int) -> dict[str, Any] | None:
    with get_session() as db:
        product = db.get(Product, product_id)
        if product is None:
            return None
        return {
            "product_id": product.id,
            "product_name": product.display_name,
            "category": product.category or "",
            "series": product.series or "",
            **offer_view(product.offer),
        }


def save_catalog_offer(
    product_id: int,
    *,
    title: str,
    description_html: str,
    image_urls: list[str],
    source: str = "manual",
    allegro_offer_id: str | None = None,
) -> bool:
    with get_session() as db:
        product = db.get(Product, product_id)
        if product is None:
            return False
        offer = product.offer
        if offer is None:
            offer = ProductOffer(product_id=product.id)
            db.add(offer)
        offer.title = title.strip()
        offer.description_html = description_html.strip() or None
        offer.image_urls = dump_image_urls(image_urls)
        offer.source = source
        if source == "allegro":
            offer.allegro_offer_id = allegro_offer_id
        offer.updated_at = datetime.now(timezone.utc).isoformat()
        db.commit()
        return True


def linked_allegro_offers(db, product_id: int) -> list[AllegroOffer]:
    size_ids = [
        row[0]
        for row in db.query(ProductSize.id).filter(ProductSize.product_id == product_id).all()
    ]
    filters = [AllegroOffer.product_id == product_id]
    if size_ids:
        filters.append(AllegroOffer.product_size_id.in_(size_ids))
    return db.query(AllegroOffer).filter(or_(*filters)).all()


def pick_allegro_source(offers: list[AllegroOffer]) -> AllegroOffer | None:
    def score(offer: AllegroOffer) -> tuple[int, int, int]:
        active = 1 if (offer.publication_status or "").upper() == "ACTIVE" else 0
        described = 1 if description_is_usable(offer.description_html) else 0
        pictured = 1 if parse_image_urls(offer.image_urls) else 0
        return (described, pictured, active)

    if not offers:
        return None
    return max(offers, key=score)


def copy_catalog_offer_from_allegro(product_id: int) -> str:
    """Skopiuj tytul, opis i zdjecia z najlepszej powiazanej oferty Allegro.

    Zwraca 'ok', 'missing_product', 'no_allegro' albo 'no_content'.
    Nie woła API Allegro. Bierze tresc juz zapisana w magazynie.
    """
    with get_session() as db:
        product = db.get(Product, product_id)
        if product is None:
            return "missing_product"
        source = pick_allegro_source(linked_allegro_offers(db, product_id))
        if source is None:
            return "no_allegro"
        images = parse_image_urls(source.image_urls)
        description = source.description_html if description_is_usable(source.description_html) else ""
        title = source.title or ""
        allegro_offer_id = source.offer_id
        if not description and not images:
            return "no_content"

    save_catalog_offer(
        product_id,
        title=title,
        description_html=description,
        image_urls=images,
        source="allegro",
        allegro_offer_id=allegro_offer_id,
    )
    return "ok"


def compose_catalog_offer_from_template(product_id: int, *, only_size: str | None = None) -> str:
    """Złóż opis z wzoru serii. Zdjęcia bierze z powiązanej oferty Allegro, jeśli są.

    Zwraca 'ok', 'missing_product' albo 'no_template'.
    """
    with get_session() as db:
        product = db.get(Product, product_id)
        if product is None:
            return "missing_product"
        template = template_for(product.category, product.series)
        if template is None or not template.publish:
            return "no_template"
        source = pick_allegro_source(linked_allegro_offers(db, product_id))
        images = public_image_urls(parse_image_urls(source.image_urls if source else None))
        color = product.color or ""
        title = offer_title(template, color=color, size=only_size)
        html = render_offer_html(template, color=color, photos=images, only_size=only_size)

    save_catalog_offer(
        product_id,
        title=title,
        description_html=html,
        image_urls=images,
        source="template",
    )
    return "ok"
