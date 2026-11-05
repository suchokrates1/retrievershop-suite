"""Tłumaczenie błędów Allegro na język dla historii statusu i Messengera."""

import json
import logging
from types import SimpleNamespace
from unittest.mock import Mock

from magazyn.allegro_api.shipment_management import AllegroShipmentError
from magazyn.db import get_session
from magazyn.models.orders import Order, OrderStatusLog
from magazyn.services.allegro_error_text import human_reason_from_exception, humanize_allegro_errors
from magazyn.services.print_agent_notifications import (
    PrintAgentNotifier,
    build_label_error_message,
)
from magazyn.services.print_agent_status import set_print_error_status


def test_polish_mobile_number_is_translated():
    text = humanize_allegro_errors(
        [
            {
                "path": "receiver.phone",
                "code": "INTERNAL_VALIDATION_ERROR",
                "message": "The contact number must be a Polish mobile number.",
            }
        ]
    )

    assert text == "Numer telefonu musi być polskim numerem komórkowym."


def test_polish_user_message_is_kept():
    text = humanize_allegro_errors(
        [
            {
                "message": "Some unknown carrier constraint",
                "userMessage": "Paczka jest za ciężka dla tej usługi.",
            }
        ]
    )

    assert text == "Paczka jest za ciężka dla tej usługi."


def test_unknown_english_error_is_wrapped():
    text = humanize_allegro_errors(
        [{"message": "The weight parameter is invalid for this service."}]
    )

    assert text == (
        "Allegro odrzuciło etykietę: The weight parameter is invalid for this service."
    )


def test_ascii_polish_message_stays_readable():
    text = humanize_allegro_errors([{"message": "Brak numeru budynku"}])

    assert text == "Brak numeru budynku."


def test_reason_from_allegro_shipment_error():
    exc = AllegroShipmentError(
        [
            {
                "message": "The contact number must be a Polish mobile number.",
                "path": "receiver.phone",
                "code": "INTERNAL_VALIDATION_ERROR",
            }
        ]
    )

    assert human_reason_from_exception(exc) == (
        "Numer telefonu musi być polskim numerem komórkowym."
    )


def test_label_error_message_includes_reason():
    text = build_label_error_message(
        "allegro_1",
        "Numer telefonu musi być polskim numerem komórkowym.",
    )

    assert "allegro_1" in text
    assert "Numer telefonu musi być polskim numerem komórkowym." in text


def test_notifier_sends_human_reason():
    response = Mock()
    response.raise_for_status = Mock()
    http_post = Mock(return_value=response)
    notifier = PrintAgentNotifier(
        logger=logging.getLogger("test"),
        config_provider=lambda: SimpleNamespace(
            page_access_token="token",
            recipient_id="recipient",
        ),
        http_post=http_post,
    )

    notifier.send_label_error_notification(
        "allegro_1",
        "Numer telefonu musi być polskim numerem komórkowym.",
    )

    payload = json.loads(http_post.call_args.kwargs["data"])
    assert "polskim numerem komórkowym" in payload["message"]["text"]
    assert payload["recipient"]["id"] == "recipient"


def test_print_error_status_replaces_generic_note(app):
    order_id = "allegro_phone_note"
    with app.app_context():
        with get_session() as db:
            db.add(Order(order_id=order_id, platform="allegro"))

        logger = logging.getLogger("test")
        set_print_error_status(
            order_id,
            "Brak etykiety - Allegro nie zwrocilo danych",
            logger,
        )
        set_print_error_status(
            order_id,
            "Numer telefonu musi być polskim numerem komórkowym.",
            logger,
        )

        with get_session() as db:
            logs = (
                db.query(OrderStatusLog)
                .filter(OrderStatusLog.order_id == order_id)
                .all()
            )

    assert len(logs) == 1
    assert logs[0].status == "blad_druku"
    assert logs[0].notes == "Numer telefonu musi być polskim numerem komórkowym."
