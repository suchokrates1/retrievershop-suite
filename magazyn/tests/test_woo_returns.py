"""Testy mostu Woo / WebToffee → zwroty magazynu."""

from __future__ import annotations

import hashlib
import hmac
import json
from decimal import Decimal
from unittest.mock import MagicMock, patch

from magazyn.db import get_session
from magazyn.models.orders import Order
from magazyn.models.returns import Return
from magazyn.services.return_refunds import check_refund_eligibility, process_refund
from magazyn.services.return_woo import (
    upsert_return_from_woo_withdrawal,
    verify_woo_return_signature,
)
from magazyn.services.woo_order_sync import import_woo_order


def test_verify_woo_return_signature(monkeypatch):
    monkeypatch.setattr(
        "magazyn.services.return_woo.settings_store.get",
        lambda key, default=None: "sekret" if "SECRET" in key else default,
    )
    body = b'{"withdrawal_id":1}'
    sig = hmac.new(b"sekret", body, hashlib.sha256).hexdigest()
    assert verify_woo_return_signature(body, sig)
    assert verify_woo_return_signature(body, f"sha256={sig}")
    assert not verify_woo_return_signature(body, "bad")


def test_upsert_return_from_woo_withdrawal_creates_and_dedups(app):
    with app.app_context():
        with get_session() as db:
            db.add(
                Order(
                    order_id="woo_9001",
                    external_order_id="9001",
                    shop_order_id=9001,
                    platform="woocommerce",
                    customer_name="Anna Woo",
                    payment_done=Decimal("100.00"),
                    delivery_price=Decimal("0.00"),
                    payment_method="Apple Pay (WooPayments)",
                )
            )
            db.commit()

        payload = {
            "withdrawal_id": 42,
            "order_id": 9001,
            "customer_name": "Anna Woo",
            "reason": "odstapienie",
            "items": [
                {"name": "Szelki L", "quantity": 1, "price_brutto": 100.0, "ean": "123"}
            ],
        }
        first = upsert_return_from_woo_withdrawal(payload)
        assert first["ok"] is True
        assert first["created"] is True
        assert first.get("instruction_token")
        assert "instrukcja-zwrotu" in (first.get("instruction_url") or "")

        second = upsert_return_from_woo_withdrawal(payload)
        assert second["ok"] is True
        assert second["created"] is False
        assert second["return_id"] == first["return_id"]

        with get_session() as db:
            rows = db.query(Return).filter(Return.order_id == "woo_9001").all()
            assert len(rows) == 1
            assert rows[0].woo_withdrawal_id == "42"
            assert rows[0].return_carrier == "WOO"
            assert rows[0].status == "pending"


def test_check_refund_eligibility_woo_ready(app, monkeypatch):
    order_id = "woo_9002"
    with app.app_context():
        with get_session() as db:
            db.add(
                Order(
                    order_id=order_id,
                    external_order_id="9002",
                    platform="woocommerce",
                    customer_name="Ewa",
                    payment_done=Decimal("278.00"),
                    delivery_price=Decimal("0.00"),
                    payment_method="Apple Pay (WooPayments)",
                    currency="PLN",
                )
            )
            db.add(
                Return(
                    order_id=order_id,
                    status="delivered",
                    customer_name="Ewa",
                    items_json=json.dumps(
                        [{"name": "Szelki", "quantity": 1, "price_brutto": 278.0}]
                    ),
                    return_carrier="WOO",
                    woo_withdrawal_id="99",
                    stock_restored=True,
                )
            )
            db.commit()

        eligible, message, details = check_refund_eligibility(order_id)
        assert eligible is True
        assert "Woo" in message
        assert details["platform"] == "woocommerce"
        assert details["total_amount"] == 278.0
        assert details["refund_channel"] == "woo"


def test_process_refund_woo_calls_rest(app, monkeypatch):
    order_id = "woo_9003"
    with app.app_context():
        with get_session() as db:
            db.add(
                Order(
                    order_id=order_id,
                    external_order_id="9003",
                    platform="woocommerce",
                    customer_name="Ola",
                    payment_done=Decimal("150.00"),
                    delivery_price=Decimal("0.00"),
                    payment_method="WooPayments",
                    currency="PLN",
                )
            )
            db.add(
                Return(
                    order_id=order_id,
                    status="delivered",
                    customer_name="Ola",
                    items_json=json.dumps(
                        [{"name": "Obroza", "quantity": 1, "price_brutto": 150.0}]
                    ),
                    return_carrier="WOO",
                    woo_withdrawal_id="100",
                    stock_restored=True,
                )
            )
            db.commit()

        monkeypatch.setattr(
            "magazyn.woocommerce_api.refunds.create_order_refund",
            lambda *a, **k: {
                "success": True,
                "refund_id": 555,
                "amount": Decimal("150.00"),
                "error": None,
            },
        )
        monkeypatch.setattr(
            "magazyn.services.invoice_service.generate_correction_invoice",
            lambda **kwargs: {"success": True, "invoice_number": "KOR/1", "errors": []},
        )

        ok, message = process_refund(order_id, delivery_cost_covered=True)
        assert ok is True
        assert "555" in message

        with get_session() as db:
            ret = db.query(Return).filter(Return.order_id == order_id).first()
            assert ret.refund_processed is True
            assert ret.status == "completed"


def test_import_woo_order_refunded_reconciles(app):
    order_id = "woo_9004"
    with app.app_context():
        with get_session() as db:
            db.add(
                Order(
                    order_id=order_id,
                    external_order_id="9004",
                    platform="woocommerce",
                    customer_name="Iga",
                    payment_done=Decimal("50.00"),
                )
            )
            db.add(
                Return(
                    order_id=order_id,
                    status="delivered",
                    return_carrier="WOO",
                    woo_withdrawal_id="101",
                    refund_processed=False,
                )
            )
            db.commit()

        result = import_woo_order(
            {
                "id": 9004,
                "number": "9004",
                "status": "refunded",
                "total": "50.00",
                "currency": "PLN",
                "billing": {"first_name": "Iga", "last_name": "K"},
                "line_items": [],
                "shipping_lines": [],
                "meta_data": [],
                "payment_method": "woocommerce_payments",
                "payment_method_title": "Karta",
                "date_created": "2026-07-22T10:00:00",
                "customer_note": "",
                "refunds": [{"id": 1, "total": "-50.00"}],
            }
        )
        assert result["skipped"] is True
        assert result["reconcile"]["ok"] is True

        with get_session() as db:
            ret = db.query(Return).filter(Return.order_id == order_id).first()
            assert ret.refund_processed is True
            assert ret.status == "completed"
