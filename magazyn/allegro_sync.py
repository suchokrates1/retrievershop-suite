from datetime import datetime, timezone
import os
import logging
from decimal import Decimal, InvalidOperation
from collections.abc import Mapping

from requests.exceptions import HTTPError

from . import allegro_api
from .models import AllegroOffer, ProductSize
from .db import get_session

logger = logging.getLogger(__name__)


def _clear_cached_tokens():
    os.environ.pop("ALLEGRO_ACCESS_TOKEN", None)
    os.environ.pop("ALLEGRO_REFRESH_TOKEN", None)


def sync_offers():
    """Synchronize offers from Allegro with local database.

    Returns
    -------
    dict
        Dictionary containing two keys:

        ``fetched``
            Number of offers fetched from Allegro across all pages.

        ``matched``
            Number of offers that were matched with local products and
            saved or updated in the database.
    """
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
        except Exception as exc:
            _clear_cached_tokens()
            logger.exception("Failed to refresh Allegro token")
            raise RuntimeError(
                "Failed to refresh Allegro token before syncing offers; "
                "please re-authorize the Allegro integration"
            ) from exc
    if not token:
        raise RuntimeError("Missing Allegro access token")

    page = 1
    fetched_count = 0
    matched_count = 0

    with get_session() as session:
        while True:
            try:
                data = allegro_api.fetch_offers(token, page)
            except HTTPError as exc:
                status_code = getattr(getattr(exc, "response", None), "status_code", None)
                if status_code == 401 and refresh:
                    try:
                        token_data = allegro_api.refresh_token(refresh)
                    except Exception as refresh_exc:
                        _clear_cached_tokens()
                        logger.exception("Failed to refresh Allegro token")
                        raise RuntimeError(
                            "Failed to refresh Allegro token after unauthorized response "
                            f"on page {page}; please re-authorize the Allegro integration"
                        ) from refresh_exc
                    new_token = token_data.get("access_token")
                    if not new_token:
                        _clear_cached_tokens()
                        message = (
                            "Failed to refresh Allegro offers on page "
                            f"{page}: missing access token"
                        )
                        logger.error(message)
                        raise RuntimeError(message)
                    token = new_token
                    os.environ["ALLEGRO_ACCESS_TOKEN"] = token
                    new_refresh = token_data.get("refresh_token")
                    if new_refresh:
                        refresh = new_refresh
                        os.environ["ALLEGRO_REFRESH_TOKEN"] = new_refresh
                    continue
                if status_code == 401 and not refresh:
                    os.environ.pop("ALLEGRO_ACCESS_TOKEN", None)
                    message = (
                        "Failed to fetch Allegro offers on page "
                        f"{page}: unauthorized and no refresh token available"
                    )
                    logger.error(message, exc_info=True)
                    raise RuntimeError(message) from exc
                detail = f"HTTP status {status_code}" if status_code else "HTTP error"
                message = (
                    "Failed to fetch Allegro offers on page "
                    f"{page}: {detail}"
                )
                logger.error(message, exc_info=True)
                raise RuntimeError(message) from exc
            except Exception as exc:
                message = f"Failed to fetch Allegro offers on page {page}"
                logger.error(message, exc_info=True)
                raise RuntimeError(message) from exc
            if not isinstance(data, Mapping):
                logger.error(
                    "Malformed response from Allegro on page %s: %r", page, data
                )
                raise RuntimeError(
                    "Failed to fetch Allegro offers on page "
                    f"{page}: malformed response from Allegro"
                )

            offers = data.get("offers") or data.get("items", {}).get("offers", [])
            if offers:
                try:
                    offers = list(offers)
                except TypeError:
                    offers = [offer for offer in offers]
            else:
                offers = []
            fetched_count += len(offers)
            for offer in offers:
                price_data = offer.get("price")
                if price_data is None:
                    selling_mode = offer.get("sellingMode")
                    if not isinstance(selling_mode, Mapping):
                        selling_mode = {}
                    price = selling_mode.get("price")
                    if not isinstance(price, Mapping):
                        price = {}
                    price_data = price.get("amount")
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

                barcode = offer.get("ean") or offer.get("barcode")
                product_size = None
                if barcode:
                    product_size = (
                        session.query(ProductSize).filter_by(barcode=barcode).first()
                    )

                product_id = product_size.product_id if product_size else None
                product_size_id = product_size.id if product_size else None

                existing = (
                    session.query(AllegroOffer)
                    .filter_by(offer_id=offer.get("id"))
                    .first()
                )
                timestamp = datetime.now(timezone.utc).isoformat()
                title = offer.get("name") or offer.get("title", "")

                if existing:
                    existing.title = title
                    existing.price = price
                    existing.product_id = product_id
                    existing.product_size_id = product_size_id
                    existing.synced_at = timestamp
                else:
                    session.add(
                        AllegroOffer(
                            offer_id=offer.get("id"),
                            title=title,
                            price=price,
                            product_id=product_id,
                            product_size_id=product_size_id,
                            synced_at=timestamp,
                        )
                    )

                if product_size:
                    matched_count += 1
            next_page = data.get("nextPage") or data.get("links", {}).get("next")
            if not next_page:
                break
            page += 1

    return {"fetched": fetched_count, "matched": matched_count}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sync_offers()
