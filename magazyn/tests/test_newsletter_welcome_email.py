"""Testy welcome newsletter (SMTP z magazynu)."""

from unittest.mock import patch

from magazyn.services.email_service import send_newsletter_welcome


def test_send_newsletter_welcome_renders_and_sends(app):
    with app.app_context():
        with patch("magazyn.services.email_service._send_html_email") as send:
            send.return_value = True
            ok = send_newsletter_welcome(
                to_email="jan@example.com",
                first_name="Jan",
                coupon_code="RS10-ABC12345",
                discount_percent=10,
                valid_days=30,
            )
            assert ok is True
            assert send.called
            kwargs = send.call_args.kwargs
            assert kwargs["to_email"] == "jan@example.com"
            assert "RS10-ABC12345" in kwargs["html_body"]
            assert "Jan" in kwargs["html_body"]
            assert "10%" in kwargs["html_body"] or "−10%" in kwargs["html_body"]
            assert "newsletter_dog_optimized" in kwargs["html_body"]
            assert "facebook.com/retrievershop" in kwargs["html_body"]
            assert "instagram.com/retrievershop.pl" in kwargs["html_body"]
            assert kwargs["subject"].startswith("Twoj rabat")


def test_newsletter_welcome_api_unauthorized(client):
    res = client.post(
        "/api/shop-mail/newsletter-welcome",
        json={"email": "a@b.c", "coupon_code": "X"},
    )
    assert res.status_code == 401


def test_newsletter_welcome_api_ok(client, app):
    with app.app_context():
        with patch("magazyn.blueprints.shop.mail_api.settings_store") as store:
            store.get.side_effect = lambda k: "secret" if k in (
                "NEWSLETTER_MAIL_SECRET",
                "WOO_WEBHOOK_SECRET",
            ) else ""
            with patch("magazyn.blueprints.shop.mail_api.send_newsletter_welcome") as send:
                send.return_value = True
                res = client.post(
                    "/api/shop-mail/newsletter-welcome",
                    json={
                        "email": "jan@example.com",
                        "first_name": "Jan",
                        "coupon_code": "RS10-TEST",
                    },
                    headers={"Authorization": "Bearer secret"},
                )
                assert res.status_code == 200
                assert res.get_json()["ok"] is True
                send.assert_called_once()
