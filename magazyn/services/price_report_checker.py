"""Sprawdzanie pojedynczej oferty do raportu cenowego."""

from __future__ import annotations


async def check_single_offer(offer: dict, cdp_host: str, cdp_port: int) -> dict:
    """Sprawdź pojedynczą ofertę przez CDP i zwróć ujednolicony wynik."""
    from ..allegro_api.offers import get_offer_badge_price
    from ..scripts.price_checker_ws import MAX_DELIVERY_DAYS, check_offer_price

    badge_price = get_offer_badge_price(offer["offer_id"])
    effective_api_price = float(badge_price) if badge_price else offer["price"]

    result = await check_offer_price(
        offer["offer_id"],
        offer["title"],
        effective_api_price,
        cdp_host,
        cdp_port,
        MAX_DELIVERY_DAYS,
    )

    competitors_all_count = result.competitors_all_count if result.success else 0

    our_siblings = []
    if result.success and result.our_other_offers:
        our_siblings = [
            {"offer_id": other_offer.offer_id, "price": other_offer.price}
            for other_offer in result.our_other_offers
            if other_offer.offer_id
        ]

    return {
        "offer_id": offer["offer_id"],
        "title": offer["title"],
        "our_price": effective_api_price,
        "product_size_id": offer["product_size_id"],
        "success": result.success,
        "error": result.error,
        "my_position": result.my_position,
        "competitors_count": len(result.competitors) if result.competitors else 0,
        "competitors_all_count": competitors_all_count,
        "our_siblings": our_siblings,
        "cheapest": {
            "price": result.cheapest_competitor.price,
            "price_with_delivery": result.cheapest_competitor.price_with_delivery,
            "seller": result.cheapest_competitor.seller,
            "url": result.cheapest_competitor.offer_url,
            "is_super_seller": result.cheapest_competitor.is_super_seller,
        } if result.cheapest_competitor else None,
    }


__all__ = ["check_single_offer"]