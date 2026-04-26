"""Przygotowanie danych widokow raportow cenowych."""

from __future__ import annotations

from typing import Any

from ..db import get_session
from ..domain.exceptions import EntityNotFoundError
from ..repositories.price_report_repository import PriceReportRepository
from .price_report_admin import get_max_discount_percent


def build_reports_list_context() -> dict[str, Any]:
    with get_session() as session:
        repository = PriceReportRepository(session)
        reports_data = []
        for report in repository.list_reports():
            items_count = repository.count_items(report.id)
            cheapest_count = repository.count_cheapest_items(report.id)
            reports_data.append(
                {
                    "id": report.id,
                    "created_at": report.created_at,
                    "completed_at": report.completed_at,
                    "status": report.status,
                    "items_checked": report.items_checked,
                    "items_total": report.items_total,
                    "total_offers": items_count,
                    "we_are_cheapest": cheapest_count,
                    "we_are_not_cheapest": items_count - cheapest_count,
                }
            )
    return {"reports": reports_data}


def _build_price_suggestion(item, has_cheaper_sibling: bool, max_discount: float):
    if has_cheaper_sibling:
        return None, "inna_aukcja_ok"
    if not item.is_cheapest and not item.competitor_price and not item.error:
        return None, "inna_aukcja_ok"
    if not item.is_cheapest and item.competitor_price and item.our_price:
        target_price = float(item.competitor_price) - 0.01
        discount_needed = ((float(item.our_price) - target_price) / float(item.our_price)) * 100
        if discount_needed <= max_discount:
            return (
                {
                    "type": "decrease",
                    "target_price": round(target_price, 2),
                    "discount_percent": round(discount_needed, 2),
                    "savings": round(float(item.our_price) - target_price, 2),
                },
                None,
            )
    elif item.is_cheapest and item.competitor_price and item.our_price:
        competitor = float(item.competitor_price)
        our_price = float(item.our_price)
        raise_target = round(competitor - 0.01, 2)
        if raise_target > our_price and our_price > 9.99:
            extra_profit = round(raise_target - our_price, 2)
            raise_percent = ((raise_target - our_price) / our_price) * 100
            if extra_profit >= 9.99:
                return (
                    {
                        "type": "increase",
                        "target_price": raise_target,
                        "raise_percent": round(raise_percent, 2),
                        "extra_profit": round(raise_target - our_price, 2),
                    },
                    None,
                )
    return None, None


def _sort_report_item(item: dict[str, Any]):
    diff = item.get("price_difference")
    note = item.get("suggestion_note")
    name = item["product_name"].lower() if item["product_name"] else ""

    if item.get("error"):
        return (4, 0, name)
    if note == "inna_aukcja_ok":
        return (2, 0, name)
    if diff is None:
        return (4, 0, name)

    diff = float(diff)
    if diff > 0:
        return (1, diff, name)
    return (3, diff, name)


def build_report_detail_context(report_id: int, filter_mode: str) -> dict[str, Any]:
    with get_session() as session:
        repository = PriceReportRepository(session)
        report = repository.get_report(report_id)
        if not report:
            raise EntityNotFoundError("Raport nie istnieje")

        items = repository.report_items(report_id, filter_mode)
        max_discount = get_max_discount_percent()
        offer_ids = [item.offer_id for item in items]
        offers = repository.offers_by_ids(offer_ids)
        offer_to_product_size = {offer.offer_id: offer.product_size_id for offer in offers}
        offer_to_product_id = {offer.offer_id: offer.product_id for offer in offers}

        product_size_offers: dict[int, list[dict[str, Any]]] = {}
        for item in repository.all_report_items(report_id):
            product_size_id = offer_to_product_size.get(item.offer_id)
            if product_size_id:
                product_size_offers.setdefault(product_size_id, []).append(
                    {
                        "offer_id": item.offer_id,
                        "is_cheapest": item.is_cheapest,
                        "our_price": item.our_price,
                    }
                )

        items_data = []
        for item in items:
            product_size_id = offer_to_product_size.get(item.offer_id)
            sibling_offers = product_size_offers.get(product_size_id, []) if product_size_id else []
            has_multiple_offers = len(sibling_offers) > 1
            has_cheaper_sibling = False
            if has_multiple_offers and item.our_price:
                our_price = float(item.our_price)
                has_cheaper_sibling = any(
                    sibling["offer_id"] != item.offer_id
                    and sibling["our_price"]
                    and float(sibling["our_price"]) < our_price
                    for sibling in sibling_offers
                )

            suggestion, suggestion_note = _build_price_suggestion(
                item,
                has_cheaper_sibling,
                max_discount,
            )
            items_data.append(
                {
                    "id": item.id,
                    "offer_id": item.offer_id,
                    "product_id": offer_to_product_id.get(item.offer_id),
                    "product_name": item.product_name,
                    "our_price": item.our_price,
                    "competitor_price": item.competitor_price,
                    "competitor_seller": item.competitor_seller,
                    "competitor_url": item.competitor_url,
                    "is_cheapest": item.is_cheapest,
                    "price_difference": item.price_difference,
                    "our_position": item.our_position,
                    "total_offers": item.total_offers,
                    "competitors_all_count": getattr(item, "competitors_all_count", None),
                    "competitor_is_super_seller": getattr(item, "competitor_is_super_seller", None),
                    "suggestion": suggestion,
                    "suggestion_note": suggestion_note,
                    "has_multiple_offers": has_multiple_offers,
                    "checked_at": item.checked_at,
                    "error": item.error,
                }
            )

        items_data.sort(key=_sort_report_item)
        stats = {
            "total": len(items),
            "cheapest": sum(1 for item in items if item.is_cheapest),
            "not_cheapest": sum(
                1 for item in items if not item.is_cheapest and item.competitor_price is not None
            ),
            "with_suggestion": sum(
                1
                for item in items_data
                if item.get("suggestion") and item["suggestion"].get("type") == "decrease"
            ),
            "with_raise_suggestion": sum(
                1
                for item in items_data
                if item.get("suggestion") and item["suggestion"].get("type") == "increase"
            ),
            "other_offer_ok": sum(
                1 for item in items_data if item.get("suggestion_note") == "inna_aukcja_ok"
            ),
            "errors": sum(1 for item in items if item.error),
        }

    return {
        "report": report,
        "items": items_data,
        "stats": stats,
        "filter_mode": filter_mode,
        "max_discount": max_discount,
    }


def current_report_status_payload() -> dict[str, Any]:
    with get_session() as session:
        report = PriceReportRepository(session).active_report()
        if not report:
            return {"status": "none"}

        return {
            "status": report.status,
            "id": report.id,
            "items_checked": report.items_checked,
            "items_total": report.items_total,
            "progress_percent": round(
                (report.items_checked / report.items_total * 100) if report.items_total > 0 else 0,
                1,
            ),
            "started_at": report.created_at.isoformat() if report.created_at else None,
        }


__all__ = [
    "build_report_detail_context",
    "build_reports_list_context",
    "current_report_status_payload",
]