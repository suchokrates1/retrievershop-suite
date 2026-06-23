"""Śledzenie dostarczenia powiadomień do klientów (email / Allegro API)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

ALLEGRO_MESSAGE_MAX_LEN = 2000
ALLEGRO_SUCCESS_STATUSES = frozenset({"DELIVERED", "VERIFYING", "SAFE"})


@dataclass(frozen=True)
class DeliveryResult:
    success: bool
    channel: str
    message_id: str | None = None
    status: str | None = None
    error: str | None = None

    def to_emails_sent_value(self) -> bool | dict[str, Any]:
        if not self.success:
            return {"sent": False, "channel": self.channel, "error": self.error}
        payload: dict[str, Any] = {"sent": True, "channel": self.channel}
        if self.message_id:
            payload["message_id"] = self.message_id
        if self.status:
            payload["status"] = self.status
        return payload


def is_allegro_proxy_email(email: str | None) -> bool:
    if not email:
        return False
    return email.strip().lower().endswith("@allegromail.pl")


def parse_emails_sent(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def was_notification_sent(order, email_type: str) -> bool:
    """Czy powiadomienie danego typu zostało pomyślnie dostarczone."""
    value = parse_emails_sent(getattr(order, "emails_sent", None)).get(email_type)
    if value is True:
        return True
    if isinstance(value, dict):
        return value.get("sent") is True
    return False


def mark_notification_sent(db, order, email_type: str, delivery: DeliveryResult) -> None:
    """Zapisz wynik dostarczenia w orders.emails_sent."""
    sent = parse_emails_sent(order.emails_sent)
    sent[email_type] = delivery.to_emails_sent_value()
    order.emails_sent = json.dumps(sent, ensure_ascii=False)
    db.flush()


def truncate_allegro_message(text: str, *, max_len: int = ALLEGRO_MESSAGE_MAX_LEN) -> str:
    text = (text or "").strip()
    if len(text) <= max_len:
        return text
    suffix = "\n\n[... wiadomość skrócona ...]"
    return text[: max_len - len(suffix)].rstrip() + suffix


# Backward-compatible aliases used across the codebase.
def _was_email_sent(order, email_type: str) -> bool:
    return was_notification_sent(order, email_type)


def _mark_email_sent(db, order, email_type: str, delivery: DeliveryResult | None = None) -> None:
    if delivery is None:
        delivery = DeliveryResult(success=True, channel="smtp")
    mark_notification_sent(db, order, email_type, delivery)


__all__ = [
    "ALLEGRO_MESSAGE_MAX_LEN",
    "ALLEGRO_SUCCESS_STATUSES",
    "DeliveryResult",
    "is_allegro_proxy_email",
    "mark_notification_sent",
    "parse_emails_sent",
    "truncate_allegro_message",
    "was_notification_sent",
    "_mark_email_sent",
    "_was_email_sent",
]
