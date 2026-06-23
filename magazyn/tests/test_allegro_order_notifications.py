"""Testy wysyłki powiadomień przez Allegro Messaging API."""

from unittest.mock import patch

import pytest

from magazyn.services.allegro_order_notifications import send_order_message
from magazyn.services.notification_delivery import (
    DeliveryResult,
    is_allegro_proxy_email,
    truncate_allegro_message,
    was_notification_sent,
)


class _FakeOrder:
    order_id = "allegro_test-uuid"
    user_login = "buyer_login"
    external_order_id = "checkout-uuid"
    email = "abc+tag@allegromail.pl"


def test_is_allegro_proxy_email():
    assert is_allegro_proxy_email("x@allegromail.pl") is True
    assert is_allegro_proxy_email("jan@test.pl") is False


def test_truncate_allegro_message():
    long_text = "a" * 2500
    trimmed = truncate_allegro_message(long_text)
    assert len(trimmed) <= 2000
    assert trimmed.endswith("skrócona ...]")


def test_was_notification_sent_legacy_and_structured():
    class Order:
        emails_sent = '{"confirmation": true, "invoice": {"sent": true, "channel": "allegro_api"}}'

    order = Order()
    assert was_notification_sent(order, "confirmation") is True
    assert was_notification_sent(order, "invoice") is True
    assert was_notification_sent(order, "delivery") is False


@patch("magazyn.services.allegro_order_notifications.settings")
@patch("magazyn.services.allegro_order_notifications.allegro_api.find_thread_id_for_login")
@patch("magazyn.services.allegro_order_notifications.allegro_api.send_thread_message")
def test_send_order_message_uses_existing_thread(mock_send, mock_find, mock_settings):
    mock_settings.ALLEGRO_ACCESS_TOKEN = "token"
    mock_find.return_value = "thread-1"
    mock_send.return_value = {"id": "msg-1", "status": "DELIVERED"}

    result = send_order_message(_FakeOrder(), "Witaj!")

    assert result.success is True
    assert result.channel == "allegro_api"
    assert result.message_id == "msg-1"
    mock_send.assert_called_once()


@patch("magazyn.services.allegro_order_notifications.settings")
@patch("magazyn.services.allegro_order_notifications.allegro_api.find_thread_id_for_login")
@patch("magazyn.services.allegro_order_notifications.allegro_api.send_new_message")
def test_send_order_message_creates_new_when_no_thread(mock_new, mock_find, mock_settings):
    mock_settings.ALLEGRO_ACCESS_TOKEN = "token"
    mock_find.return_value = None
    mock_new.return_value = {"id": "msg-2", "status": "VERIFYING"}

    result = send_order_message(_FakeOrder(), "Potwierdzenie zamówienia")

    assert result.success is True
    mock_new.assert_called_once_with(
        "token",
        "buyer_login",
        "checkout-uuid",
        "Potwierdzenie zamówienia",
        attachment_ids=None,
    )


@patch("magazyn.services.email_service.send_order_message")
@patch("magazyn.services.email_service._send_html_email")
def test_deliver_routes_allegromail_to_api(mock_smtp, mock_allegro, app):
    mock_allegro.return_value = DeliveryResult(
        success=True, channel="allegro_api", message_id="m1", status="DELIVERED"
    )
    with app.app_context():
        from magazyn.services.email_service import deliver_customer_notification

        order = _FakeOrder()
        result = deliver_customer_notification(
            order,
            subject="Test",
            html_body="<p>Hello</p>",
            text_body="Hello",
        )
        assert result.success is True
        assert result.channel == "allegro_api"
        mock_allegro.assert_called_once()
        mock_smtp.assert_not_called()


@patch("magazyn.services.email_service.send_order_message")
@patch("magazyn.services.email_service._send_html_email")
def test_deliver_uses_smtp_for_regular_email(mock_smtp, mock_allegro, app):
    mock_smtp.return_value = True
    with app.app_context():
        from magazyn.services.email_service import deliver_customer_notification

        class Order:
            email = "jan@test.pl"

        result = deliver_customer_notification(
            Order(),
            subject="Test",
            html_body="<p>Hi</p>",
        )
        assert result.success is True
        assert result.channel == "smtp"
        mock_smtp.assert_called_once()
        mock_allegro.assert_not_called()
