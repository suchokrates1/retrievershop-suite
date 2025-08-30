from datetime import datetime
import os
import logging

from . import allegro_api
from .models import AllegroOffer, ProductSize
from .db import get_session

logger = logging.getLogger(__name__)


def sync_offers():
    """Synchronize offers from Allegro with local database."""
    token = os.getenv("ALLEGRO_ACCESS_TOKEN")
    if not token:
        refresh = os.getenv("ALLEGRO_REFRESH_TOKEN")
        if refresh:
            try:
                data = allegro_api.refresh_token(refresh)
                token = data.get("access_token")
            except Exception:
                logger.exception("Failed to refresh Allegro token")
                raise
    if not token:
        raise RuntimeError("Missing Allegro access token")

    page = 1
    with get_session() as session:
        while True:
            data = allegro_api.fetch_offers(token, page)
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
                price = float(price_data) if price_data is not None else 0.0
                allegro_offer = AllegroOffer(
                    offer_id=offer.get("id"),
                    title=offer.get("name") or offer.get("title", ""),
                    price=price,
                    product_id=ps.product_id,
                    synced_at=datetime.utcnow().isoformat(),
                )
                session.merge(allegro_offer)
            next_page = data.get("nextPage") or data.get("links", {}).get("next")
            if not next_page:
                break
            page += 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sync_offers()
