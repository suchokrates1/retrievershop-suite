import logging

from .allegro_api import fetch_product_listing
from .config import settings
from .db import get_session
from .models import ProductSize, AllegroOffer
from .notifications import send_messenger

logger = logging.getLogger(__name__)


def check_prices() -> None:
    """Check Allegro listings for lower competitor prices.

    For each locally known offer, fetch public listings from Allegro based on
    its EAN barcode.  If a competitor offers the product at a lower price than
    ours, send an alert via :func:`notifications.send_messenger`.
    """
    with get_session() as session:
        rows = (
            session.query(AllegroOffer, ProductSize)
            .join(ProductSize, AllegroOffer.product_size_id == ProductSize.id)
            .all()
        )

        offers_by_barcode: dict[str, list[tuple[float, str]]] = {}
        for offer, ps in rows:
            barcode = ps.barcode
            own_price = offer.price
            if not barcode or own_price is None:
                continue
            offers_by_barcode.setdefault(barcode, []).append((own_price, offer.offer_id))

        for barcode, offers in offers_by_barcode.items():
            try:
                listing = fetch_product_listing(barcode)
            except Exception as exc:  # pragma: no cover - network errors
                logger.error("Failed to fetch listing for %s: %s", barcode, exc)
                continue

            competitor_prices = []
            for item in listing:
                seller = item.get("seller") or {}
                seller_id = seller.get("id")
                if (
                    not seller_id
                    or seller_id == settings.ALLEGRO_SELLER_ID
                    or seller_id in settings.ALLEGRO_EXCLUDED_SELLERS
                ):
                    continue
                price_str = (
                    item.get("sellingMode", {})
                    .get("price", {})
                    .get("amount")
                )
                try:
                    price = float(price_str)
                except (TypeError, ValueError):
                    continue
                competitor_prices.append(price)

            if not competitor_prices:
                continue
            lowest = min(competitor_prices)
            for own_price, offer_id in offers:
                if lowest < own_price:
                    send_messenger(
                        f"⚠️ Niższa cena dla {barcode} (oferta {offer_id}): {lowest:.2f} < {own_price:.2f}"
                    )


if __name__ == "__main__":
    check_prices()
