import logging
from datetime import datetime, timezone
from decimal import Decimal

from .config import settings
from .db import get_session
from .domain import allegro_prices
from .models import ProductSize, AllegroOffer
from .notifications import send_messenger
from .allegro_scraper import fetch_competitors_for_offer, parse_price_amount

logger = logging.getLogger(__name__)

COMPETITOR_SUFFIX = "::competitor"


def check_prices() -> dict:
    """Check Allegro listings for lower competitor prices.

    For each locally known offer, fetch public listings from Allegro by
    inspecting the public offer page with Selenium. If a competitor offers the
    product at a lower price than ours, send an alert via
    :func:`notifications.send_messenger` and record price history samples for
    subsequent trend analysis.
    """
    alerts: list[tuple[str, Decimal, Decimal]] = []

    with get_session() as session:
        rows = (
            session.query(AllegroOffer, ProductSize)
            .join(ProductSize, AllegroOffer.product_size_id == ProductSize.id)
            .all()
        )

        offers_by_barcode: dict[str, list[tuple[Decimal, str, int]]] = {}
        for offer, ps in rows:
            barcode = ps.barcode
            own_price = offer.price
            if not barcode or own_price is None:
                continue
            offers_by_barcode.setdefault(barcode, []).append(
                (own_price, offer.offer_id, ps.id)
            )

        for barcode, offers in offers_by_barcode.items():
            timestamp_dt = datetime.now(timezone.utc)
            for own_price, offer_id, product_size_id in offers:
                allegro_prices.record_price_point(
                    session,
                    offer_id=offer_id,
                    product_size_id=product_size_id,
                    price=own_price,
                    recorded_at=timestamp_dt,
                )
            try:
                first_offer_id = offers[0][1]
                competitor_offers, scrape_logs = fetch_competitors_for_offer(
                    first_offer_id,
                    stop_seller=settings.ALLEGRO_SELLER_NAME,
                )
                for entry in scrape_logs:
                    logger.debug(
                        "Selenium log for %s (EAN %s): %s",
                        first_offer_id,
                        barcode,
                        entry,
                    )
            except Exception as exc:  # pragma: no cover - network errors
                logger.error(
                    "Failed to fetch competitor listing for %s (%s): %s",
                    barcode,
                    offers[0][1],
                    exc,
                )
                continue

            competitor_prices = []
            for offer_data in competitor_offers:
                seller_name = (offer_data.seller or "").strip().lower()
                if (
                    settings.ALLEGRO_SELLER_NAME
                    and seller_name
                    and seller_name == settings.ALLEGRO_SELLER_NAME.lower()
                ):
                    continue
                price_value = parse_price_amount(offer_data.price)
                if price_value is None:
                    continue
                competitor_prices.append(price_value)

            if not competitor_prices:
                continue
            lowest = min(competitor_prices)
            for own_price, offer_id, product_size_id in offers:
                competitor_offer_id = f"{offer_id}{COMPETITOR_SUFFIX}"
                allegro_prices.record_price_point(
                    session,
                    offer_id=competitor_offer_id,
                    product_size_id=product_size_id,
                    price=lowest,
                    recorded_at=timestamp_dt,
                )
                if lowest < own_price:
                    send_messenger(
                        f"⚠️ Niższa cena dla {barcode} (oferta {offer_id}): {lowest:.2f} < {own_price:.2f}"
                    )
                    alerts.append((offer_id, own_price, lowest))

        session.flush()
        trend_report = allegro_prices.generate_trend_report(session)

    if trend_report:
        logger.info(
            "Generated Allegro competitor price trend report with %d entries",
            len(trend_report),
        )

    return {"alerts": len(alerts), "trend_report": trend_report}


if __name__ == "__main__":
    check_prices()
