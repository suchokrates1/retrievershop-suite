"""Testy API faktury PDF dla sklepu WP."""

from __future__ import annotations

import hashlib
import hmac
from decimal import Decimal
from unittest.mock import MagicMock, patch

from magazyn.db import get_session
from magazyn.models.orders import Order


def _auth_headers(secret: str = "sekret", body: bytes = b"") -> dict:
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return {
        "Authorization": f"Bearer {secret}",
        "X-RS-Invoice-Signature": sig,
    }


def test_invoice_status_unauthorized(client, monkeypatch):
    monkeypatch.setattr(
        "magazyn.blueprints.shop.invoice_api.settings_store.get",
        lambda key, default=None: "sekret" if "SECRET" in key else default,
    )
    resp = client.get("/api/shop/orders/123/invoice/status")
    assert resp.status_code == 401


def test_invoice_status_available(client, app, monkeypatch):
    monkeypatch.setattr(
        "magazyn.blueprints.shop.invoice_api.settings_store.get",
        lambda key, default=None: "sekret" if "SECRET" in key else default,
    )
    with app.app_context():
        with get_session() as db:
            db.add(
                Order(
                    order_id="woo_7771",
                    external_order_id="7771",
                    shop_order_id=7771,
                    platform="woocommerce",
                    payment_done=Decimal("50.00"),
                    delivery_price=Decimal("0.00"),
                    wfirma_invoice_id=42,
                    wfirma_invoice_number="FV 1/07/2026",
                )
            )
            db.commit()

    resp = client.get(
        "/api/shop/orders/7771/invoice/status",
        headers=_auth_headers(),
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["available"] is True
    assert data["invoice_number"] == "FV 1/07/2026"


def test_invoice_status_missing(client, app, monkeypatch):
    monkeypatch.setattr(
        "magazyn.blueprints.shop.invoice_api.settings_store.get",
        lambda key, default=None: "sekret" if "SECRET" in key else default,
    )
    with app.app_context():
        with get_session() as db:
            db.add(
                Order(
                    order_id="woo_7772",
                    external_order_id="7772",
                    shop_order_id=7772,
                    platform="woocommerce",
                    payment_done=Decimal("50.00"),
                    delivery_price=Decimal("0.00"),
                )
            )
            db.commit()

    resp = client.get(
        "/api/shop/orders/7772/invoice/status",
        headers=_auth_headers(),
    )
    assert resp.status_code == 200
    assert resp.get_json()["available"] is False


def test_invoice_pdf_download(client, app, monkeypatch):
    monkeypatch.setattr(
        "magazyn.blueprints.shop.invoice_api.settings_store.get",
        lambda key, default=None: "sekret" if "SECRET" in key else default,
    )
    pdf = b"%PDF-1.4 " + b"x" * 200
    with app.app_context():
        with get_session() as db:
            db.add(
                Order(
                    order_id="woo_7773",
                    external_order_id="7773",
                    shop_order_id=7773,
                    platform="woocommerce",
                    payment_done=Decimal("50.00"),
                    delivery_price=Decimal("0.00"),
                    wfirma_invoice_id=99,
                    wfirma_invoice_number="FV 9/07/2026",
                )
            )
            db.commit()

    mock_client = MagicMock()
    with patch(
        "magazyn.wfirma_api.WFirmaClient.from_settings",
        return_value=mock_client,
    ), patch(
        "magazyn.wfirma_api.download_invoice_pdf",
        return_value=pdf,
    ) as dl:
        resp = client.get(
            "/api/shop/orders/7773/invoice.pdf",
            headers=_auth_headers(),
        )

    assert resp.status_code == 200
    assert resp.data == pdf
    assert resp.mimetype == "application/pdf"
    assert "FV 9_07_2026.pdf" in resp.headers.get("Content-Disposition", "")
    dl.assert_called_once_with(mock_client, 99)
