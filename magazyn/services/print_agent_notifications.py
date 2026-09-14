"""Powiadomienia Messenger uzywane przez agenta drukowania."""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Dict

import requests


MESSENGER_ENDPOINT = "https://graph.facebook.com/v17.0/me/messages"


def build_messenger_message(data: Dict[str, Any], print_success: bool = True) -> str:
    """Zbuduj tresc powiadomienia o zamowieniu i statusie etykiety."""
    label_status = "Etykieta gotowa" if print_success else "Blad drukowania etykiety"
    products = "".join(
        f"- {product['name']} (x{product['quantity']})\n"
        for product in data.get("products", [])
    )

    return (
        f"Nowe zamowienie od: {data.get('customer', '-')}\n"
        f"Produkty:\n"
        f"{products}"
        f"Wysylka: {data.get('shipping', '-')}\n"
        f"Kurier: {data.get('courier_code', '-')}\n"
        f"Platforma: {data.get('platform', '-')}\n"
        f"ID: {data.get('order_id', '-')}\n"
        f"Status etykiety: {label_status}"
    )


def notify_messenger(
    send_message: Callable[..., None],
    data: Dict[str, Any],
    print_success: bool,
) -> None:
    """Wywolaj funkcje wysylki, toleruj uproszczone monkeypatche testow."""
    try:
        send_message(data, print_success=print_success)
    except TypeError:
        send_message(data)


class PrintAgentNotifier:
    """Obsluga powiadomien agenta drukowania."""

    def __init__(
        self,
        *,
        logger: logging.Logger,
        config_provider: Callable[[], Any],
        http_post: Callable[..., Any] = requests.post,
    ):
        self.logger = logger
        self.config_provider = config_provider
        self.http_post = http_post
        self.error_counts: Dict[str, int] = {}

    def should_send_error_notification(self, order_id: str) -> bool:
        """Powiadom przy pierwszej i dziesiatej probie braku etykiety."""
        count = self.error_counts.get(order_id, 0)
        return count == 0 or count == 9

    def increment_error_notification(self, order_id: str) -> None:
        self.error_counts[order_id] = self.error_counts.get(order_id, 0) + 1

    def send_label_error_notification(self, order_id: str) -> None:
        """Wyslij krotkie powiadomienie o braku etykiety."""
        try:
            config = self.config_provider()
            message = f"Brak etykiety do zamowienia nr: {order_id}"
            response = self.http_post(
                MESSENGER_ENDPOINT,
                headers={
                    "Authorization": f"Bearer {config.page_access_token}",
                    "Content-Type": "application/json",
                },
                data=json.dumps(
                    {
                        "recipient": {"id": config.recipient_id},
                        "message": {"text": message},
                    }
                ),
                timeout=10,
            )
            response.raise_for_status()
            self.increment_error_notification(order_id)
        except Exception as exc:
            self.logger.error("Blad wysylania wiadomosci: %s", exc)

    def send_messenger_message(
        self,
        data: Dict[str, Any],
        print_success: bool = True,
    ) -> None:
        try:
            config = self.config_provider()
            response = self.http_post(
                MESSENGER_ENDPOINT,
                headers={
                    "Authorization": f"Bearer {config.page_access_token}",
                    "Content-Type": "application/json",
                },
                data=json.dumps(
                    {
                        "recipient": {"id": config.recipient_id},
                        "message": {"text": build_messenger_message(data, print_success)},
                    }
                ),
                timeout=10,
            )
            response.raise_for_status()
        except Exception as exc:
            self.logger.error("Blad wysylania wiadomosci: %s", exc)


__all__ = [
    "MESSENGER_ENDPOINT",
    "PrintAgentNotifier",
    "build_messenger_message",
    "notify_messenger",
]