from datetime import datetime, timezone
import logging
import re
import unicodedata
from decimal import Decimal, InvalidOperation
from collections.abc import Mapping
from urllib.parse import urlparse, parse_qs

from requests.exceptions import HTTPError
from sqlalchemy import or_

from . import allegro_api
from .models import AllegroOffer, Product, ProductSize
from .db import get_session
from .parsing import parse_offer_title, normalize_color
from .env_tokens import clear_allegro_tokens, update_allegro_tokens
from .metrics import ALLEGRO_SYNC_ERRORS_TOTAL
from .domain import allegro_prices
from .settings_store import SettingsPersistenceError, settings_store

logger = logging.getLogger(__name__)


_COLOR_COMPONENT_PATTERN = re.compile(r"[\\s/\\-]+")


def _normalize_color_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    stripped = "".join(char for char in normalized if not unicodedata.combining(char))
    return stripped.casefold().strip()


def _normalized_product_color_components(value: str) -> set[str]:
    components: set[str] = set()
    for component in _COLOR_COMPONENT_PATTERN.split(value or ""):
        component = component.strip()
        if not component:
            continue
        normalized_component = normalize_color(component)
        key = _normalize_color_key(normalized_component)
        if key:
            components.add(key)
    return components


def _raise_settings_store_read_only(exc: SettingsPersistenceError) -> None:
    guidance = (
        "Cannot modify Allegro credentials because the settings store is read-only. "
        "Update them manually in the configuration file and rerun the synchronisation."
    )
    ALLEGRO_SYNC_ERRORS_TOTAL.labels(reason="settings_store").inc()
    logger.error(guidance, exc_info=True)
    raise RuntimeError(guidance) from exc


def _clear_cached_tokens():
    try:
        clear_allegro_tokens()
    except SettingsPersistenceError as exc:
        _raise_settings_store_read_only(exc)


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

        ``trend_report``
            Aggregated price trend entries generated from the stored history
            samples.
    """
    token = settings_store.get("ALLEGRO_ACCESS_TOKEN")
    refresh = settings_store.get("ALLEGRO_REFRESH_TOKEN")
    if not token and refresh:
        try:
            token_data = allegro_api.refresh_token(refresh)
            token = token_data.get("access_token")
            new_refresh = token_data.get("refresh_token")
            if new_refresh:
                refresh = new_refresh
            if token:
                update_allegro_tokens(token, refresh)
        except SettingsPersistenceError as exc:
            _raise_settings_store_read_only(exc)
        except Exception as exc:
            _clear_cached_tokens()
            logger.exception("Failed to refresh Allegro token")
            ALLEGRO_SYNC_ERRORS_TOTAL.labels(reason="token_refresh").inc()
            raise RuntimeError(
                "Failed to refresh Allegro token before syncing offers; "
                "please re-authorize the Allegro integration"
            ) from exc
    if not token:
        raise RuntimeError("Missing Allegro access token")

    offset = 0
    limit = 100
    fetched_count = 0
    matched_count = 0
    trend_report: list = []

    with get_session() as session:
        while True:
            try:
                data = allegro_api.fetch_offers(token, offset=offset, limit=limit)
            except HTTPError as exc:
                status_code = getattr(getattr(exc, "response", None), "status_code", None)
                if status_code == 401:
                    latest_token = settings_store.get("ALLEGRO_ACCESS_TOKEN")
                    latest_refresh = settings_store.get("ALLEGRO_REFRESH_TOKEN")
                    if latest_token and latest_token != token:
                        token = latest_token
                        refresh = latest_refresh
                        continue
                    if latest_refresh and latest_refresh != refresh:
                        refresh = latest_refresh
                    if refresh:
                        try:
                            token_data = allegro_api.refresh_token(refresh)
                        except Exception as refresh_exc:
                            _clear_cached_tokens()
                            logger.exception("Failed to refresh Allegro token")
                            ALLEGRO_SYNC_ERRORS_TOTAL.labels(reason="token_refresh").inc()
                            raise RuntimeError(
                                "Failed to refresh Allegro token after unauthorized response "
                                f"at offset {offset}; please re-authorize the Allegro integration"
                            ) from refresh_exc
                        new_token = token_data.get("access_token")
                        if not new_token:
                            _clear_cached_tokens()
                            message = (
                                "Failed to refresh Allegro offers at offset "
                                f"{offset}: missing access token"
                            )
                            ALLEGRO_SYNC_ERRORS_TOTAL.labels(reason="token_refresh").inc()
                            logger.error(message)
                            raise RuntimeError(message)
                        token = new_token
                        new_refresh = token_data.get("refresh_token")
                        if new_refresh:
                            refresh = new_refresh
                        try:
                            update_allegro_tokens(token, refresh)
                        except SettingsPersistenceError as persistence_exc:
                            _raise_settings_store_read_only(persistence_exc)
                        continue
                    _clear_cached_tokens()
                    message = (
                        "Failed to fetch Allegro offers at offset "
                        f"{offset}: unauthorized and no refresh token available"
                    )
                    ALLEGRO_SYNC_ERRORS_TOTAL.labels(reason="http").inc()
                    logger.error(message, exc_info=True)
                    raise RuntimeError(message) from exc
                detail = f"HTTP status {status_code}" if status_code else "HTTP error"
                message = (
                    "Failed to fetch Allegro offers at offset "
                    f"{offset}: {detail}"
                )
                ALLEGRO_SYNC_ERRORS_TOTAL.labels(reason="http").inc()
                logger.error(message, exc_info=True)
                raise RuntimeError(message) from exc
            except Exception as exc:
                message = f"Failed to fetch Allegro offers at offset {offset}"
                ALLEGRO_SYNC_ERRORS_TOTAL.labels(reason="unexpected").inc()
                logger.error(message, exc_info=True)
                raise RuntimeError(message) from exc
            if not isinstance(data, Mapping):
                logger.error(
                    "Malformed response from Allegro at offset %s: %r", offset, data
                )
                raise RuntimeError(
                    "Failed to fetch Allegro offers at offset "
                    f"{offset}: malformed response from Allegro"
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

                title = offer.get("name") or offer.get("title", "")
                name, color, size = parse_offer_title(title)
                color = normalize_color(color)
                normalized_offer_color_key = _normalize_color_key(color)

                base_query = (
                    session.query(ProductSize)
                    .join(Product)
                    .filter(Product.name == name, ProductSize.size == size)
                )

                if color:
                    product_sizes = base_query.all()
                else:
                    product_sizes = (
                        base_query.filter(
                            or_(Product.color == "", Product.color.is_(None))
                        ).all()
                    )

                product_size = None
                if color:
                    for candidate in product_sizes:
                        product_color_value = candidate.product.color or ""
                        if not product_color_value.strip():
                            continue
                        normalized_product_color = normalize_color(product_color_value)
                        if (
                            _normalize_color_key(normalized_product_color)
                            == normalized_offer_color_key
                        ):
                            product_size = candidate
                            break
                    if not product_size and normalized_offer_color_key:
                        for candidate in product_sizes:
                            product_color_value = candidate.product.color or ""
                            component_keys = _normalized_product_color_components(
                                product_color_value
                            )
                            if normalized_offer_color_key in component_keys:
                                product_size = candidate
                                break
                else:
                    product_size = product_sizes[0] if product_sizes else None

                product_id = product_size.product_id if product_size else None
                product_size_id = product_size.id if product_size else None

                existing = (
                    session.query(AllegroOffer)
                    .filter_by(offer_id=offer.get("id"))
                    .first()
                )
                timestamp_dt = datetime.now(timezone.utc)
                timestamp = timestamp_dt.isoformat()

                if existing:
                    existing.title = title
                    existing.price = price
                    if product_size is not None or existing.product_size_id is None:
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

                allegro_prices.record_price_point(
                    session,
                    offer_id=offer.get("id"),
                    product_size_id=product_size_id,
                    price=price,
                    recorded_at=timestamp_dt,
                )

                if product_size:
                    matched_count += 1
            next_page = data.get("nextPage") or data.get("links", {}).get("next")
            if isinstance(next_page, list):
                next_page = next_page[0] if next_page else None
            if not next_page:
                break
            next_offset, next_limit = _extract_pagination(next_page, limit)
            if next_offset is None or next_offset == offset:
                break
            offset = next_offset
            limit = next_limit

        session.flush()
        trend_report = allegro_prices.generate_trend_report(session)

    if trend_report:
        logger.info("Generated Allegro price trend report with %d entries", len(trend_report))

    return {"fetched": fetched_count, "matched": matched_count, "trend_report": trend_report}


def _parse_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _extract_from_href(href):
    try:
        query = parse_qs(urlparse(href).query)
    except Exception:
        return None, None
    offset = None
    limit = None
    offset_values = query.get("offset")
    if offset_values:
        offset = _parse_int(offset_values[0])
    limit_values = query.get("limit")
    if limit_values:
        limit = _parse_int(limit_values[0])
    return offset, limit


def _extract_pagination(next_data, current_limit):
    next_offset = None
    next_limit = current_limit

    if isinstance(next_data, Mapping):
        next_offset = _parse_int(next_data.get("offset"))
        new_limit = _parse_int(next_data.get("limit"))
        if new_limit is not None:
            next_limit = new_limit
        href = next_data.get("href")
        if href:
            href_offset, href_limit = _extract_from_href(href)
            if href_limit is not None:
                next_limit = href_limit
            if next_offset is None:
                next_offset = href_offset
    elif isinstance(next_data, str):
        href_offset, href_limit = _extract_from_href(next_data)
        if href_limit is not None:
            next_limit = href_limit
        next_offset = href_offset

    return next_offset, next_limit


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sync_offers()

