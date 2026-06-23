"""Wysyłka powiadomień transakcyjnych przez Centrum Wiadomości Allegro."""

from __future__ import annotations

import logging

from requests.exceptions import HTTPError, RequestException

from .. import allegro_api
from ..config import settings
from .notification_delivery import (
    ALLEGRO_SUCCESS_STATUSES,
    DeliveryResult,
    truncate_allegro_message,
)

logger = logging.getLogger(__name__)


def upload_message_attachment(
    token: str,
    filename: str,
    file_content: bytes,
    content_type: str = "application/pdf",
) -> str:
    """Prześlij załącznik do Centrum Wiadomości i zwróć attachment_id."""
    return allegro_api.upload_attachment_complete(
        token,
        filename,
        file_content,
        content_type,
    )


def send_order_message(
    order,
    text: str,
    *,
    attachment: bytes | None = None,
    attachment_filename: str | None = None,
) -> DeliveryResult:
    """
    Wyślij wiadomość do kupującego przez Allegro Messaging API.

    Preferuje odpowiedź w istniejącym wątku; jeśli brak — tworzy nową wiadomość
    powiązaną z zamówieniem (POST /messaging/messages).
    """
    token = getattr(settings, "ALLEGRO_ACCESS_TOKEN", None)
    if not token:
        return DeliveryResult(
            success=False,
            channel="allegro_api",
            error="Brak tokenu Allegro",
        )

    buyer_login = (order.user_login or "").strip()
    checkout_id = (order.external_order_id or "").strip()
    if not buyer_login:
        return DeliveryResult(
            success=False,
            channel="allegro_api",
            error="Brak user_login kupującego",
        )
    if not checkout_id:
        return DeliveryResult(
            success=False,
            channel="allegro_api",
            error="Brak external_order_id (checkout-form)",
        )

    message_text = truncate_allegro_message(text)
    attachment_ids: list[str] = []
    if attachment and attachment_filename:
        try:
            content_type = (
                "application/pdf"
                if attachment_filename.lower().endswith(".pdf")
                else "application/octet-stream"
            )
            attachment_ids.append(
                upload_message_attachment(
                    token,
                    attachment_filename,
                    attachment,
                    content_type,
                )
            )
        except (HTTPError, RequestException) as exc:
            logger.warning(
                "Nie udało się przesłać załącznika dla %s: %s",
                order.order_id,
                exc,
            )
            return DeliveryResult(
                success=False,
                channel="allegro_api",
                error=f"Błąd załącznika: {exc}",
            )

    try:
        thread_id = allegro_api.find_thread_id_for_login(token, buyer_login)
        if thread_id:
            response = allegro_api.send_thread_message(
                token,
                thread_id,
                message_text,
                attachment_ids=attachment_ids or None,
            )
        else:
            response = allegro_api.send_new_message(
                token,
                buyer_login,
                checkout_id,
                message_text,
                attachment_ids=attachment_ids or None,
            )
    except HTTPError as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        logger.warning(
            "Allegro odrzuciło wiadomość dla %s (HTTP %s): %s",
            order.order_id,
            status,
            exc,
        )
        return DeliveryResult(
            success=False,
            channel="allegro_api",
            error=f"HTTP {status}",
        )
    except RequestException as exc:
        logger.error(
            "Błąd sieci przy wysyłce wiadomości Allegro dla %s: %s",
            order.order_id,
            exc,
        )
        return DeliveryResult(
            success=False,
            channel="allegro_api",
            error=str(exc),
        )

    message_id = response.get("id")
    status = response.get("status")
    success = status in ALLEGRO_SUCCESS_STATUSES if status else bool(message_id)
    if success:
        logger.info(
            "Wiadomość Allegro wysłana dla %s (message_id=%s, status=%s)",
            order.order_id,
            message_id,
            status,
        )
    else:
        logger.warning(
            "Wiadomość Allegro dla %s ma nieoczekiwany status: %s",
            order.order_id,
            status,
        )

    return DeliveryResult(
        success=success,
        channel="allegro_api",
        message_id=message_id,
        status=status,
        error=None if success else f"status={status}",
    )


__all__ = ["send_order_message", "upload_message_attachment"]
