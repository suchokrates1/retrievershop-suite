"""Mutacje pojedynczych pozycji raportow cenowych."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from ..db import get_session
from ..repositories.price_report_repository import PriceReportRepository

logger = logging.getLogger(__name__)


def _decrease_suggestion(item, max_discount: float) -> dict[str, Any] | None:
    if not item.is_cheapest and item.competitor_price and item.our_price:
        target_price = float(item.competitor_price) - 0.01
        discount_needed = ((float(item.our_price) - target_price) / float(item.our_price)) * 100
        if discount_needed <= max_discount:
            return {
                "type": "decrease",
                "target_price": round(target_price, 2),
                "discount_percent": round(discount_needed, 2),
            }
    elif item.is_cheapest and item.competitor_price and item.our_price:
        competitor = float(item.competitor_price)
        our_price = float(item.our_price)
        raise_target = round(competitor - 0.01, 2)
        if raise_target > our_price and our_price > 9.99:
            raise_percent = ((raise_target - our_price) / our_price) * 100
            if raise_percent >= 1.0:
                return {
                    "type": "increase",
                    "target_price": raise_target,
                    "raise_percent": round(raise_percent, 2),
                    "extra_profit": round(raise_target - our_price, 2),
                }
    return None


def recheck_report_item(
    item_id: int,
    *,
    max_discount_provider: Callable[[], float],
) -> dict[str, Any]:
    from ..allegro_api.offers import get_offer_badge_price, get_offer_details
    from ..scripts.price_checker_ws import CDP_HOST, CDP_PORT, MAX_DELIVERY_DAYS, check_offer_price

    try:
        with get_session() as session:
            repository = PriceReportRepository(session)
            item = repository.get_item(item_id)
            if not item:
                return {"success": False, "error": "Nie znaleziono pozycji"}

            offer_id = item.offer_id
            old_our_price = float(item.our_price) if item.our_price else None
            title = item.product_name
            offer = repository.allegro_offer(offer_id)
            product_size_id = offer.product_size_id if offer else None
            cheaper_sibling = None
            if product_size_id and old_our_price:
                cheaper_sibling = repository.cheaper_sibling(
                    product_size_id=product_size_id,
                    offer_id=offer_id,
                    price=old_our_price,
                )

        if cheaper_sibling:
            with get_session() as session:
                item = PriceReportRepository(session).get_item(item_id)
                item.is_cheapest = False
                item.competitor_price = None
                item.competitor_seller = None
                item.competitor_url = None
                item.error = None
                item.checked_at = datetime.now()
                session.commit()

            return {
                "success": True,
                "price_updated": False,
                "sibling_ok": True,
                "data": {
                    "our_price": old_our_price,
                    "competitor_price": None,
                    "competitor_seller": None,
                    "is_cheapest": False,
                    "price_difference": None,
                    "our_position": None,
                    "total_offers": None,
                    "suggestion": None,
                    "suggestion_note": "inna_aukcja_ok",
                    "error": None,
                    "message": (
                        f"Tansza siostra: {cheaper_sibling.offer_id} "
                        f"({float(cheaper_sibling.price)} zl)"
                    ),
                },
            }

        our_offer_data = get_offer_details(offer_id)
        current_our_price = old_our_price
        price_updated = False

        if our_offer_data.get("success") and our_offer_data.get("price"):
            current_our_price = float(our_offer_data["price"])
            if old_our_price and abs(current_our_price - old_our_price) > 0.001:
                price_updated = True
                logger.info("Cena oferty %s zmienila sie: %s -> %s", offer_id, old_our_price, current_our_price)

        badge_price = get_offer_badge_price(offer_id)
        if badge_price:
            current_our_price = float(badge_price)
            logger.info("Oferta %s ma cene kampanii (badge): %s", offer_id, current_our_price)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(
                check_offer_price(
                    offer_id,
                    title,
                    current_our_price,
                    CDP_HOST,
                    CDP_PORT,
                    MAX_DELIVERY_DAYS,
                )
            )
        finally:
            loop.close()

        with get_session() as session:
            item = PriceReportRepository(session).get_item(item_id)
            effective_price = current_our_price
            if effective_price and old_our_price and abs(effective_price - old_our_price) > 0.001:
                price_updated = True
                item.our_price = Decimal(str(effective_price))
                logger.info("Cena oferty %s zaktualizowana: %s -> %s", offer_id, old_our_price, effective_price)
            elif price_updated:
                item.our_price = Decimal(str(current_our_price))

            if result.success and result.cheapest_competitor:
                item.competitor_price = Decimal(str(result.cheapest_competitor.price))
                item.competitor_seller = result.cheapest_competitor.seller
                item.competitor_url = result.cheapest_competitor.offer_url
                item.competitor_is_super_seller = getattr(result.cheapest_competitor, "is_super_seller", None)
                item.our_position = result.my_position
                item.total_offers = len(result.competitors) + 1 if result.competitors else 1
                item.competitors_all_count = getattr(result, "competitors_all_count", None)
                if item.our_price:
                    item.is_cheapest = item.our_price <= item.competitor_price
                    item.price_difference = float(item.our_price - item.competitor_price)
                item.error = None
            elif result.success and not result.cheapest_competitor:
                item.competitor_price = None
                item.competitor_seller = None
                item.competitor_url = None
                item.competitor_is_super_seller = None
                item.our_position = 1
                item.total_offers = 1
                item.competitors_all_count = getattr(result, "competitors_all_count", 0)
                item.is_cheapest = True
                item.price_difference = None
                item.error = None
            else:
                item.error = result.error or "Blad sprawdzania"

            item.checked_at = datetime.now()
            session.commit()
            suggestion = _decrease_suggestion(item, max_discount_provider())

            return {
                "success": True,
                "price_updated": price_updated,
                "old_price": old_our_price,
                "data": {
                    "our_price": float(item.our_price) if item.our_price else None,
                    "competitor_price": float(item.competitor_price) if item.competitor_price else None,
                    "competitor_seller": item.competitor_seller,
                    "is_cheapest": item.is_cheapest,
                    "price_difference": item.price_difference,
                    "our_position": item.our_position,
                    "total_offers": item.total_offers,
                    "suggestion": suggestion,
                    "error": item.error,
                },
            }
    except Exception as exc:
        logger.error("Blad ponownego sprawdzania: %s", exc, exc_info=True)
        return {"success": False, "error": str(exc)}


def change_report_item_price(item_id: int, new_price_raw: str | None) -> dict[str, Any]:
    from ..allegro_api.offers import change_offer_price, get_offer_price

    if not new_price_raw:
        return {"success": False, "error": "Podaj nowa cene"}

    try:
        new_price = Decimal(new_price_raw)
    except (InvalidOperation, ValueError):
        return {"success": False, "error": "Nieprawidlowa cena"}

    try:
        with get_session() as session:
            item = PriceReportRepository(session).get_item(item_id)
            if not item:
                return {"success": False, "error": "Nie znaleziono pozycji"}

            offer_id = item.offer_id
            old_price = item.our_price
            offer_name = item.product_name

        result = change_offer_price(offer_id, new_price)
        if not result.get("success"):
            logger.warning(
                "Nieudana zmiana ceny oferty %s (%s): %s",
                offer_id,
                offer_name,
                result.get("error", "nieznany blad"),
            )
            return {"success": False, "error": result.get("error", "Blad API Allegro")}

        verify_result = get_offer_price(offer_id)
        if not verify_result.get("success"):
            logger.warning(
                "Zmiana ceny oferty %s wyslana, ale weryfikacja nieudana: %s",
                offer_id,
                verify_result.get("error", "nieznany blad"),
            )
            verified_price = new_price
        else:
            verified_price = verify_result.get("price")
            if abs(verified_price - new_price) > Decimal("0.01"):
                logger.error(
                    "Rozbieznosc ceny oferty %s: zadana=%s, potwierdzona=%s",
                    offer_id,
                    new_price,
                    verified_price,
                )
                return {
                    "success": False,
                    "error": f"Cena na Allegro ({verified_price}) rozni sie od zadanej ({new_price})",
                }

        with get_session() as session:
            repository = PriceReportRepository(session)
            item = repository.get_item(item_id)
            if item:
                item.our_price = verified_price
                if item.competitor_price:
                    item.is_cheapest = verified_price <= item.competitor_price
                    item.price_difference = float(verified_price - item.competitor_price)

            offer = repository.allegro_offer(offer_id)
            if offer:
                offer.price = verified_price

            session.commit()

        logger.info(
            "Zmiana ceny oferty %s (%s): %s -> %s zl [zweryfikowano przez API]",
            offer_id,
            offer_name,
            old_price,
            verified_price,
        )
        return {
            "success": True,
            "message": f"Zmieniono cene z {old_price} na {verified_price} zl",
            "verified": True,
        }
    except Exception as exc:
        logger.error("Blad zmiany ceny: %s", exc, exc_info=True)
        return {"success": False, "error": str(exc)}


__all__ = ["change_report_item_price", "recheck_report_item"]