from datetime import datetime, timezone
import logging
import re
import unicodedata
from decimal import Decimal, InvalidOperation
from collections.abc import Mapping
from urllib.parse import urlparse, parse_qs

import requests
from requests.exceptions import HTTPError
from sqlalchemy import or_

from .db import get_session, configure_engine
from .settings_store import SettingsPersistenceError, settings_store
from .config import settings
from .allegro_api import fetch_offers
from . import allegro_api

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
    print("sync_offers called")
    from .models import AllegroOffer, Product, ProductSize, AllegroPriceHistory
    from .db import get_session
    import logging
    
    logger = logging.getLogger(__name__)
    
    try:
        access_token = settings_store.get("ALLEGRO_ACCESS_TOKEN")
        if not access_token:
            logger.error("No Allegro access token available")
            return {"error": "No access token"}
        
        logger.info("Starting Allegro offers sync")
        
        # Fetch offers from Allegro API
        offset = 0
        limit = 100
        all_offers = []
        
        while True:
            response = allegro_api.fetch_offers(access_token, offset=offset, limit=limit)
            # Handle different response formats
            if "offers" in response:
                offers = response["offers"]
            elif "items" in response and "offers" in response["items"]:
                offers = response["items"]["offers"]
            else:
                offers = []
            all_offers.extend(offers)
            
            # Check if there are more pages
            if len(offers) < limit:
                break
            offset += limit
        
        logger.info(f"Fetched {len(all_offers)} offers from Allegro")
        
        with get_session() as db:
            # Clear existing offers
            db.query(AllegroOffer).delete()
            
            matched_count = 0
            
            for offer_data in all_offers:
                offer_id = offer_data["id"]
                title = offer_data["name"]
                price = Decimal(offer_data["sellingMode"]["price"]["amount"])
                
                # Try to match with products
                product_size_id = None
                product_id = None
                
                # Parse title to extract product info
                # Simple parsing - remove size and color from end
                title_lower = title.lower()
                potential_size = None
                
                # Check for size at the end
                size_pattern = r'\s+(xs|s|m|l|xl|xxl)$'
                import re
                match = re.search(size_pattern, title_lower)
                if match:
                    potential_size = match.group(1).upper()
                    title_without_size = title_lower[:match.start()].strip()
                else:
                    title_without_size = title_lower
                
                # Remove common color words
                color_words = ['czerwony', 'niebieski', 'zielony', 'czarny', 'biały', 'żółty', 'fioletowy', 'pomarańczowy', 'szary', 'różowy']
                potential_name_parts = title_without_size.split()
                filtered_parts = [part for part in potential_name_parts if part not in color_words]
                potential_name = " ".join(filtered_parts)
                
                # Try to find matching product
                product_query = db.query(Product).filter(Product.name.ilike(f"%{potential_name}%")).first()
                if product_query:
                    product_id = product_query.id
                    # Try to find matching size
                    if potential_size:
                        size_query = db.query(ProductSize).filter(
                            ProductSize.product_id == product_id,
                            ProductSize.size == potential_size
                        ).first()
                        if size_query:
                            product_size_id = size_query.id
                            matched_count += 1
                
                offer = AllegroOffer(
                    offer_id=offer_id,
                    title=title,
                    price=price,
                    product_size_id=product_size_id,
                    product_id=product_id,
                    publication_status=offer_data.get("publication", {}).get("status", "ACTIVE")
                )
                db.add(offer)
                
                # Create price history entry
                from datetime import datetime, timezone
                price_history = AllegroPriceHistory(
                    offer_id=offer_id,
                    product_size_id=product_size_id,
                    price=price,
                    recorded_at=datetime.now(timezone.utc),
                    competitor_price=None,  # No competitor data yet
                    competitor_seller=None,
                    competitor_url=None,
                    competitor_delivery_days=None
                )
                db.add(price_history)
            
            db.commit()
        
        return {
            "fetched": len(all_offers),
            "matched": matched_count,
            "trend_report": [{"offer_id": offer_id, "title": title, "price": float(price)} for offer_id, title, price in [(o["id"], o["name"], o["sellingMode"]["price"]["amount"]) for o in all_offers]]
        }
        
    except Exception as e:
        logger.error(f"Error syncing offers: {e}")
        return {"error": str(e)}


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
    print("Starting allegro_sync")
    logging.basicConfig(level=logging.INFO)
    try:
        print("Reloading settings_store...")
        settings_store.reload()
        print("Reload successful")
    except Exception as e:
        print(f"Error in reload: {e}")
        raise
    try:
        print(f"DB_PATH: {settings.DB_PATH}")
        print("Configuring engine...")
        configure_engine(settings.DB_PATH)
        print("Engine configured, starting sync...")
    except Exception as e:
        print(f"Error during setup: {e}")
        raise
    sync_offers()

