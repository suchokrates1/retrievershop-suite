import logging
import os
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Optional
from urllib.parse import unquote, urlparse

from .config import settings
from .db import get_session
from .domain import allegro_prices
from .models import ProductSize, AllegroOffer
from .notifications import send_messenger
from .allegro_scraper import fetch_competitors_for_offer, parse_price_amount

logger = logging.getLogger(__name__)


def _resolve_db_path(db_path: str | os.PathLike[str]) -> Optional[Path]:
    """Return the filesystem path for ``db_path`` if it can be resolved."""

    try:
        if isinstance(db_path, Path):
            return db_path
        if isinstance(db_path, os.PathLike):
            return Path(db_path)
        if isinstance(db_path, str):
            if db_path.startswith("file:"):
                parsed = urlparse(db_path)
                if parsed.scheme != "file":
                    return None
                if "mode=ro" in (parsed.query or "").lower():
                    return Path(unquote(parsed.path))
                return Path(unquote(parsed.path))
            if db_path:
                return Path(db_path)
    except (OSError, ValueError):  # pragma: no cover - defensive
        return None
    return None


def _is_db_writable(db_path: str | os.PathLike[str]) -> bool:
    """Return ``True`` when the SQLite database appears writable."""

    if isinstance(db_path, str) and db_path.startswith("file:"):
        if "mode=ro" in db_path.lower():
            return False

    resolved = _resolve_db_path(db_path)
    if resolved is None:
        # When the path is a SQLite URI without a filesystem component we
        # conservatively assume it is writable so normal execution can
        # proceed. Any OperationalError will be handled later.
        return True

    try:
        if resolved.exists() and not os.access(resolved, os.W_OK):
            return False
        parent = resolved.parent if resolved.parent != Path("") else Path(".")
        if not os.access(parent, os.W_OK):
            return False
    except OSError:  # pragma: no cover - defensive
        return False
    return True

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

    can_record_history = _is_db_writable(settings.DB_PATH)
    if not can_record_history:
        logger.warning(
            "Database %s is read-only; competitor price history will not be recorded",
            settings.DB_PATH,
        )

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
            if can_record_history:
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
                if can_record_history:
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

        if can_record_history:
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
