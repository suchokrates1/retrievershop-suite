"""Pomocnicze operacje powiadomien dla zwrotow."""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Dict, List, Optional

from ..models.orders import Order
from ..models.returns import Return
from ..notifications import send_messenger

logger = logging.getLogger(__name__)


def get_order_products_summary(order: Order) -> List[Dict[str, Any]]:
    """Pobierz podsumowanie produktow z zamowienia dla zwrotu."""
    return [
        {
            "ean": product.ean,
            "name": product.name,
            "quantity": product.quantity,
            "product_size_id": product.product_size_id,
        }
        for product in order.products
    ]


def build_return_notification_message(return_record: Return) -> str:
    """Zbuduj tekst powiadomienia Messenger o nowym zwrocie."""
    items = json.loads(return_record.items_json) if return_record.items_json else []
    items_text = ", ".join(
        f"{item.get('name', 'Nieznany produkt')} x{item.get('quantity', 1)}"
        for item in items
    )

    message = (
        f"[ZWROT] Klient {return_record.customer_name or 'Nieznany'} "
        f"zglosil zwrot: {items_text}"
    )

    if return_record.return_tracking_number:
        message += f"\nNumer sledzenia: {return_record.return_tracking_number}"

    return message


def send_return_notification(
    return_record: Return,
    *,
    send_message: Callable[[str], bool] = send_messenger,
    log: Optional[logging.Logger] = None,
) -> bool:
    """Wyslij powiadomienie Messenger o nowym zwrocie."""
    active_logger = log or logger
    try:
        success = send_message(build_return_notification_message(return_record))
        if success:
            active_logger.info("Wyslano powiadomienie o zwrocie #%s", return_record.id)
        else:
            active_logger.warning("Nie udalo sie wyslac powiadomienia o zwrocie #%s", return_record.id)

        return success
    except Exception as exc:
        active_logger.error("Blad wysylania powiadomienia o zwrocie: %s", exc)
        return False


__all__ = [
    "build_return_notification_message",
    "get_order_products_summary",
    "send_return_notification",
]