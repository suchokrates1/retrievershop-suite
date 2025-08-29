"""Utilities for synchronizing Allegro offers with local database."""

import os
from typing import Optional

from .allegro_api import refresh_token, fetch_offers
from .db import get_session
from .models import AllegroOffer, ProductSize


def _get_access_token() -> str:
    """Return access token using refresh token from environment."""
    refresh = os.getenv("ALLEGRO_REFRESH_TOKEN")
    if not refresh:
        raise RuntimeError("ALLEGRO_REFRESH_TOKEN not set")
    data = refresh_token(refresh)
    return data["access_token"]


def sync_offers() -> None:
    """Synchronize offers from Allegro into the local database.

    Retrieves all offers using Allegro API, tries to match them with
    ``ProductSize`` records by barcode and stores them in the
    ``AllegroOffer`` table. Existing records are updated.
    """
    access_token = _get_access_token()
    page = 1
    while True:
        data = fetch_offers(access_token, page=page)
        offers = data.get("offers") or []
        if not offers:
            break
        with get_session() as session:
            for offer in offers:
                offer_id: Optional[str] = offer.get("id")
                if not offer_id:
                    continue
                barcode = offer.get("ean") or offer.get("barcode")
                product_size = None
                if barcode:
                    product_size = (
                        session.query(ProductSize)
                        .filter(ProductSize.barcode == barcode)
                        .first()
                    )
                allegro_offer = session.get(AllegroOffer, offer_id)
                if allegro_offer:
                    allegro_offer.name = offer.get("name")
                    allegro_offer.barcode = barcode
                    allegro_offer.product_size = product_size
                else:
                    session.add(
                        AllegroOffer(
                            id=offer_id,
                            name=offer.get("name"),
                            barcode=barcode,
                            product_size=product_size,
                        )
                    )
        page += 1


def main() -> None:
    """Entry point for CLI usage."""
    sync_offers()


if __name__ == "__main__":
    main()
