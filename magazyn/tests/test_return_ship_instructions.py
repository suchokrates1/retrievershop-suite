"""Testy instrukcji odesłania zwrotu Woo (self / InPost gated)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

from magazyn.db import get_session
from magazyn.inpost_api.returns import returns_credentials_configured
from magazyn.models.orders import Order
from magazyn.models.returns import Return
from magazyn.services.return_ship_instructions import (
    METHOD_INPOST,
    METHOD_SELF,
    choose_return_ship_method,
    ensure_instruction_token,
    get_instructions_payload,
)
from magazyn.services.return_woo import upsert_return_from_woo_withdrawal


def _seed_woo_order(order_id: str = "woo_9101", phone: str = "500600700"):
    with get_session() as db:
        db.add(
            Order(
                order_id=order_id,
                external_order_id=order_id.replace("woo_", ""),
                shop_order_id=int(order_id.replace("woo_", "")),
                platform="woocommerce",
                customer_name="Anna Test",
                email="anna@example.com",
                phone=phone,
                payment_done=Decimal("100.00"),
                delivery_price=Decimal("0.00"),
            )
        )
        db.commit()


def test_upsert_creates_instruction_token(app):
    with app.app_context():
        _seed_woo_order("woo_9101")
        result = upsert_return_from_woo_withdrawal(
            {
                "withdrawal_id": 501,
                "order_id": 9101,
                "customer_name": "Anna Test",
                "reason": "test",
                "items": [{"name": "Szelki", "quantity": 1}],
            }
        )
        assert result["ok"] is True
        assert result["instruction_token"]
        assert "instrukcja-zwrotu" in result["instruction_url"]

        with get_session() as db:
            row = db.query(Return).filter(Return.order_id == "woo_9101").one()
            assert row.return_instruction_token == result["instruction_token"]
            assert row.return_ship_deadline is not None


def test_choose_self_ship(app, monkeypatch):
    with app.app_context():
        _seed_woo_order("woo_9102")
        upsert_return_from_woo_withdrawal(
            {
                "withdrawal_id": 502,
                "order_id": 9102,
                "customer_name": "Anna Test",
                "items": [],
            }
        )
        with get_session() as db:
            row = db.query(Return).filter(Return.order_id == "woo_9102").one()
            token = row.return_instruction_token

        sent = {"n": 0}

        def _fake_deliver(*a, **k):
            sent["n"] += 1
            from magazyn.services.email_service import DeliveryResult

            return DeliveryResult(success=True, channel="smtp")

        monkeypatch.setattr(
            "magazyn.services.return_ship_instructions.deliver_customer_notification",
            _fake_deliver,
        )
        result = choose_return_ship_method(token, METHOD_SELF)
        assert result["ok"] is True
        assert result["method"] == METHOD_SELF
        assert result["address"]["city"] == "Legnica"
        assert sent["n"] == 1

        again = choose_return_ship_method(token, METHOD_SELF)
        assert again["ok"] is True
        assert again.get("already") is True
        assert sent["n"] == 1


def test_choose_inpost_unavailable_without_credentials(app, monkeypatch):
    with app.app_context():
        monkeypatch.setattr(
            "magazyn.services.return_ship_instructions.returns_credentials_configured",
            lambda: False,
        )
        _seed_woo_order("woo_9103")
        upsert_return_from_woo_withdrawal(
            {"withdrawal_id": 503, "order_id": 9103, "items": []}
        )
        with get_session() as db:
            token = (
                db.query(Return)
                .filter(Return.order_id == "woo_9103")
                .one()
                .return_instruction_token
            )
        result = choose_return_ship_method(token, METHOD_INPOST)
        assert result["ok"] is False
        assert result["error"] == "inpost_unavailable"


def test_choose_inpost_phone_required(app, monkeypatch):
    with app.app_context():
        monkeypatch.setattr(
            "magazyn.services.return_ship_instructions.returns_credentials_configured",
            lambda: True,
        )
        _seed_woo_order("woo_9104", phone="")
        upsert_return_from_woo_withdrawal(
            {"withdrawal_id": 504, "order_id": 9104, "items": []}
        )
        with get_session() as db:
            token = (
                db.query(Return)
                .filter(Return.order_id == "woo_9104")
                .one()
                .return_instruction_token
            )
        result = choose_return_ship_method(token, METHOD_INPOST)
        assert result["ok"] is False
        assert result["error"] == "phone_required"


def test_choose_inpost_creates_code(app, monkeypatch):
    with app.app_context():
        monkeypatch.setattr(
            "magazyn.services.return_ship_instructions.returns_credentials_configured",
            lambda: True,
        )
        monkeypatch.setattr(
            "magazyn.services.return_ship_instructions.create_return_ticket",
            lambda **kwargs: {
                "id": "uuid-1",
                "code": "8840221068",
                "expirationDate": (datetime.utcnow() + timedelta(days=14)).isoformat()
                + "Z",
                "trackingNumber": "600000997430727012159810",
            },
        )
        sent = {"n": 0}

        def _fake_deliver(*a, **k):
            sent["n"] += 1
            from magazyn.services.email_service import DeliveryResult

            return DeliveryResult(success=True, channel="smtp")

        monkeypatch.setattr(
            "magazyn.services.return_ship_instructions.deliver_customer_notification",
            _fake_deliver,
        )
        _seed_woo_order("woo_9105")
        upsert_return_from_woo_withdrawal(
            {"withdrawal_id": 505, "order_id": 9105, "items": []}
        )
        with get_session() as db:
            token = (
                db.query(Return)
                .filter(Return.order_id == "woo_9105")
                .one()
                .return_instruction_token
            )
        result = choose_return_ship_method(token, METHOD_INPOST, pack_size="A")
        assert result["ok"] is True
        assert result["method"] == METHOD_INPOST
        assert result["return_code"] == "8840221068"
        assert sent["n"] == 1

        with get_session() as db:
            row = db.query(Return).filter(Return.order_id == "woo_9105").one()
            assert row.return_carrier == "INPOST"
            assert row.return_code == "8840221068"


def test_api_get_and_choose_self(app, client, monkeypatch):
    with app.app_context():
        _seed_woo_order("woo_9106")
        upsert_return_from_woo_withdrawal(
            {"withdrawal_id": 506, "order_id": 9106, "items": []}
        )
        with get_session() as db:
            token = (
                db.query(Return)
                .filter(Return.order_id == "woo_9106")
                .one()
                .return_instruction_token
            )

        monkeypatch.setattr(
            "magazyn.services.return_ship_instructions.deliver_customer_notification",
            lambda *a, **k: type("R", (), {"success": True, "channel": "smtp"})(),
        )

        r = client.get(f"/api/shop/return-instructions/{token}")
        assert r.status_code == 200
        data = r.get_json()
        assert data["ok"] is True
        assert data["inpost_available"] is False or isinstance(
            data["inpost_available"], bool
        )

        r2 = client.post(
            f"/api/shop/return-instructions/{token}/choose",
            json={"method": "self"},
        )
        assert r2.status_code == 200
        assert r2.get_json()["method"] == "self"


def test_returns_credentials_helper(monkeypatch):
    monkeypatch.setattr(
        "magazyn.inpost_api.returns.settings_store.get",
        lambda key, default=None: "",
    )
    assert returns_credentials_configured() is False
