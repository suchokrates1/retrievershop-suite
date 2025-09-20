from datetime import datetime, timezone
import os
import logging
from decimal import Decimal, InvalidOperation

from requests.exceptions import HTTPError

from . import allegro_api
from .models import AllegroOffer, ProductSize
from .db import get_session

logger = logging.getLogger(__name__)


def sync_offers():
    """Synchronize offers from Allegro with local database."""
    token = os.getenv("ALLEGRO_ACCESS_TOKEN")
    refresh = os.getenv("ALLEGRO_REFRESH_TOKEN")
    if not token and refresh:
        try:
            token_data = allegro_api.refresh_token(refresh)
            token = token_data.get("access_token")
            if token:
                os.environ["ALLEGRO_ACCESS_TOKEN"] = token
            new_refresh = token_data.get("refresh_token")
            if new_refresh:
                refresh = new_refresh
                os.environ["ALLEGRO_REFRESH_TOKEN"] = new_refresh
        except Exception:
            logger.exception("Failed to refresh Allegro token")
            raise
    if not token:
        raise RuntimeError("Missing Allegro access token")

    page = 1
    with get_session() as session:
        while True:
            try:
                data = allegro_api.fetch_offers(token, page)
            except HTTPError as exc:
                status_code = getattr(getattr(exc, "response", None), "status_code", None)
                if status_code == 401 and refresh:
                    try:
                        token_data = allegro_api.refresh_token(refresh)
                    except Exception:
                        logger.exception("Failed to refresh Allegro token")
                        break
                    new_token = token_data.get("access_token")
                    if not new_token:
                        logger.error(
                            "Failed to refresh offers on page %s due to missing access token",
                            page,
                        )
                        break
                    token = new_token
                    os.environ["ALLEGRO_ACCESS_TOKEN"] = token
                    new_refresh = token_data.get("refresh_token")
                    if new_refresh:
                        refresh = new_refresh
                        os.environ["ALLEGRO_REFRESH_TOKEN"] = new_refresh
                    continue
                logger.error("Failed to fetch offers on page %s", page, exc_info=True)
                break
            except Exception:
                logger.error("Failed to fetch offers on page %s", page, exc_info=True)
                break
            offers = data.get("offers") or data.get("items", {}).get("offers", [])
            for offer in offers:
                barcode = offer.get("ean") or offer.get("barcode")
                if not barcode:
                    continue
                ps = session.query(ProductSize).filter_by(barcode=barcode).first()
                if not ps:
                    continue
                price_data = (
                    offer.get("price")
                    or offer.get("sellingMode", {}).get("price", {}).get("amount")
                )
                if price_data is not None:
                    try:
                        price = Decimal(price_data).quantize(Decimal("0.01"))
                    except (TypeError, ValueError, InvalidOperation):
                        logger.error(
                            "Invalid price data for offer %s: %r",
                            offer.get("id"),
                            price_data,
                        )
                        continue
                else:
                    price = Decimal("0.00")
                existing = (
                    session.query(AllegroOffer)
                    .filter_by(offer_id=offer.get("id"))
                    .first()
                )
                timestamp = datetime.now(timezone.utc).isoformat()
                if existing:
                    existing.title = offer.get("name") or offer.get("title", "")
                    existing.price = price
                    existing.product_id = ps.product_id
                    existing.product_size_id = ps.id
                    existing.synced_at = timestamp
                else:
                    session.add(
                        AllegroOffer(
                            offer_id=offer.get("id"),
                            title=offer.get("name") or offer.get("title", ""),
                            price=price,
                            product_id=ps.product_id,
                            product_size_id=ps.id,
                            synced_at=timestamp,
                        )
                    )
            next_page = data.get("nextPage") or data.get("links", {}).get("next")
            if not next_page:
                break
            page += 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sync_offers()
