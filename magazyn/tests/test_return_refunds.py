"""Testy dla refundow recznych zwrotow bez customer-return Allegro."""

from datetime import datetime, timezone

from magazyn.models.orders import Order, OrderStatusLog
from magazyn.models.returns import Return
from magazyn.allegro_api.refunds import (
    build_partial_refund_details,
    build_refund_line_items,
    initiate_refund,
)
from magazyn.services.return_refunds import check_refund_eligibility, process_refund


PARTIAL_CHECKOUT_FORM = {
    "summary": {"totalToPay": {"amount": "457.00", "currency": "PLN"}},
    "delivery": {"cost": {"amount": "0.00", "currency": "PLN"}},
    "payment": {"id": "payment-partial"},
    "lineItems": [
        {
            "id": "line-red-l",
            "quantity": 1,
            "offer": {
                "id": "18484956938",
                "name": "Szelki guard dla dużego psa Truelove Front Line Premium L czerwone",
            },
            "price": {"amount": "228.00", "currency": "PLN"},
        },
        {
            "id": "line-red-xl",
            "quantity": 1,
            "offer": {
                "id": "18549480073",
                "name": "Szelki guard dla dużego psa Truelove Front Line Premium XL czerwone",
            },
            "price": {"amount": "229.00", "currency": "PLN"},
        },
    ],
}

PARTIAL_RETURN_ITEMS = [
    {
        "offerId": "18484956938",
        "quantity": 1,
        "name": "Szelki guard dla dużego psa Truelove Front Line Premium L czerwone",
        "price": {"amount": "228", "currency": "PLN"},
    }
]


def test_check_refund_eligibility_allows_manual_return_without_allegro_return_id(app, monkeypatch):
    order_id = "allegro_test_manual_return"

    checkout_form = {
        "summary": {"totalToPay": {"amount": "229.00", "currency": "PLN"}},
        "delivery": {"cost": {"amount": "0.00", "currency": "PLN"}},
        "lineItems": [
            {
                "id": "line-1",
                "quantity": 1,
                "price": {"amount": "229.00", "currency": "PLN"},
            }
        ],
    }

    with app.app_context():
        from magazyn.db import get_session

        with get_session() as db:
            db.add(
                Order(
                    order_id=order_id,
                    external_order_id="cf-test-manual-return",
                    platform="allegro",
                    customer_name="Jan Testowy",
                    payment_done=229,
                    delivery_method="Allegro Automat DHL BOX 24/7 (AD)",
                )
            )
            db.add(
                OrderStatusLog(
                    order_id=order_id,
                    status="zwrot",
                    timestamp=datetime.now(timezone.utc),
                )
            )
            db.add(
                Return(
                    order_id=order_id,
                    status="delivered",
                    customer_name="Jan Testowy",
                    allegro_return_id=None,
                    items_json="[]",
                )
            )
            db.commit()

        monkeypatch.setattr("magazyn.services.return_refunds.settings_store.settings.ALLEGRO_ACCESS_TOKEN", "token")
        monkeypatch.setattr("magazyn.services.return_refunds.allegro_api.get_checkout_form", lambda token, external_id: (checkout_form, None))

        eligible, message, details = check_refund_eligibility(order_id)

    assert eligible is True
    assert "ręczny zwrot" in message.lower()
    assert details["allegro_status"] == "MANUAL_RETURN"
    assert details["total_amount"] == 229.0
    assert details["allegro_return_id"] is None


def test_initiate_refund_normalizes_custom_reason_to_refund(monkeypatch):
    captured = {}

    checkout_form = {
        "payment": {"id": "payment-1"},
        "lineItems": [
            {
                "id": "line-1",
                "quantity": 1,
            }
        ],
    }

    class DummyResponse:
        status_code = 201

        def json(self):
            return {
                "id": "refund-1",
                "totalValue": {"amount": "229.00", "currency": "PLN"},
            }

    def fake_request_with_retry(method, url, *, endpoint, **kwargs):
        captured["endpoint"] = endpoint
        captured["payload"] = kwargs["json"]
        return DummyResponse()

    monkeypatch.setattr(
        "magazyn.allegro_api.refunds.get_checkout_form",
        lambda access_token, order_external_id: (checkout_form, None),
    )
    monkeypatch.setattr(
        "magazyn.allegro_api.refunds._request_with_retry",
        fake_request_with_retry,
    )

    success, message, response_data = initiate_refund(
        access_token="token",
        return_id=None,
        order_external_id="order-1",
        reason="Nie odebrano przesylki",
    )

    assert success is True
    assert "zainicjowany" in message.lower()
    assert response_data["id"] == "refund-1"
    assert captured["endpoint"] == "payments-refunds"
    assert captured["payload"]["reason"] == "REFUND"


def test_check_refund_eligibility_allows_stock_restored_allegro_return(app, monkeypatch):
    order_id = "allegro_test_stock_restored_override"

    checkout_form = {
        "summary": {"totalToPay": {"amount": "229.00", "currency": "PLN"}},
        "delivery": {"cost": {"amount": "0.00", "currency": "PLN"}},
        "lineItems": [
            {
                "id": "line-1",
                "quantity": 1,
                "price": {"amount": "229.00", "currency": "PLN"},
            }
        ],
    }

    with app.app_context():
        from magazyn.db import get_session

        with get_session() as db:
            db.add(
                Order(
                    order_id=order_id,
                    external_order_id="cf-test-stock-restored",
                    platform="allegro",
                    customer_name="Jan Testowy",
                    payment_done=229,
                    delivery_method="Allegro Automat DHL BOX 24/7 (AD)",
                )
            )
            db.add(
                Return(
                    order_id=order_id,
                    status="delivered",
                    customer_name="Jan Testowy",
                    allegro_return_id="return-123",
                    stock_restored=True,
                    items_json="[]",
                )
            )
            db.commit()

        monkeypatch.setattr("magazyn.services.return_refunds.settings_store.settings.ALLEGRO_ACCESS_TOKEN", "token")
        monkeypatch.setattr("magazyn.services.return_refunds.allegro_api.get_checkout_form", lambda token, external_id: (checkout_form, None))
        monkeypatch.setattr(
            "magazyn.services.return_refunds.allegro_api.get_customer_return",
            lambda token, return_id: (_ for _ in ()).throw(AssertionError("get_customer_return nie powinno byc wywolane")),
        )

        eligible, message, details = check_refund_eligibility(order_id)

    assert eligible is True
    assert "przywrocenie stanu" in message.lower()
    assert details["allegro_status"] == "STOCK_RESTORED"
    assert details["total_amount"] == 229.0
    assert details["allegro_return_id"] == "return-123"


def test_process_refund_uses_checkout_form_path_for_stock_restored_allegro_return(app, monkeypatch):
    order_id = "allegro_test_process_stock_restored_override"
    captured = {}

    checkout_form = {
        "summary": {"totalToPay": {"amount": "229.00", "currency": "PLN"}},
        "delivery": {"cost": {"amount": "0.00", "currency": "PLN"}},
        "payment": {"id": "payment-1"},
        "lineItems": [{"id": "line-1", "quantity": 1}],
    }

    with app.app_context():
        from magazyn.db import get_session

        with get_session() as db:
            db.add(
                Order(
                    order_id=order_id,
                    external_order_id="cf-test-process-stock-restored",
                    platform="allegro",
                    customer_name="Jan Testowy",
                    payment_done=229,
                    delivery_method="Allegro Automat DHL BOX 24/7 (AD)",
                )
            )
            db.add(
                Return(
                    order_id=order_id,
                    status="delivered",
                    customer_name="Jan Testowy",
                    allegro_return_id="return-123",
                    stock_restored=True,
                    items_json="[]",
                )
            )
            db.commit()

    monkeypatch.setattr("magazyn.services.return_refunds.settings_store.settings.ALLEGRO_ACCESS_TOKEN", "token")
    monkeypatch.setattr("magazyn.services.return_refunds.allegro_api.get_checkout_form", lambda token, external_id: (checkout_form, None))
    monkeypatch.setattr(
        "magazyn.services.return_refunds.allegro_api.get_customer_return",
        lambda token, return_id: (_ for _ in ()).throw(AssertionError("get_customer_return nie powinno byc wywolane")),
    )

    def fake_initiate_refund(**kwargs):
        captured.update(kwargs)
        return False, "expected failure", None

    monkeypatch.setattr("magazyn.services.return_refunds.allegro_api.initiate_refund", fake_initiate_refund)

    success, message = process_refund(order_id)

    assert success is False
    assert "expected failure" in message
    assert captured["return_id"] is None
    assert captured["order_external_id"] == "cf-test-process-stock-restored"


def test_build_refund_line_items_supports_partial_return_by_offer_id():
    line_items, total_amount, currency, error = build_refund_line_items(
        PARTIAL_RETURN_ITEMS,
        PARTIAL_CHECKOUT_FORM,
    )

    assert error is None
    assert total_amount == 228.0
    assert currency == "PLN"
    assert line_items == [{"id": "line-red-l", "type": "QUANTITY", "quantity": 1}]


def test_build_partial_refund_details_marks_partial_return():
    details, error = build_partial_refund_details(
        PARTIAL_RETURN_ITEMS,
        PARTIAL_CHECKOUT_FORM,
    )

    assert error is None
    assert details["total_amount"] == 228.0
    assert details["is_partial"] is True
    assert len(details["line_items"]) == 1


def test_check_refund_eligibility_uses_partial_amount_for_allegro_return(app, monkeypatch):
    order_id = "allegro_test_partial_return"

    with app.app_context():
        from magazyn.db import get_session

        with get_session() as db:
            db.add(
                Order(
                    order_id=order_id,
                    external_order_id="cf-test-partial-return",
                    platform="allegro",
                    customer_name="Jan Testowy",
                    payment_done=457,
                    delivery_method="Allegro Automat DHL BOX 24/7 (AD)",
                )
            )
            db.add(
                Return(
                    order_id=order_id,
                    status="delivered",
                    customer_name="Jan Testowy",
                    allegro_return_id="return-partial-1",
                    items_json='[{"name": "Szelki guard dla dużego psa Truelove Front Line Premium L czerwone", "quantity": 1}]',
                )
            )
            db.commit()

        monkeypatch.setattr("magazyn.services.return_refunds.settings_store.settings.ALLEGRO_ACCESS_TOKEN", "token")
        monkeypatch.setattr(
            "magazyn.services.return_refunds.allegro_api.get_customer_return",
            lambda token, return_id: (
                {
                    "status": "DELIVERED",
                    "items": PARTIAL_RETURN_ITEMS,
                    "refund": {},
                },
                None,
            ),
        )
        monkeypatch.setattr(
            "magazyn.services.return_refunds.allegro_api.get_checkout_form",
            lambda token, external_id: (PARTIAL_CHECKOUT_FORM, None),
        )

        eligible, message, details = check_refund_eligibility(order_id)

    assert eligible is True
    assert details["total_amount"] == 228.0
    assert details["is_partial"] is True
    assert len(details["returned_items"]) == 1


def test_process_refund_passes_partial_line_items_to_allegro(app, monkeypatch):
    order_id = "allegro_test_process_partial_return"
    captured = {}

    with app.app_context():
        from magazyn.db import get_session

        with get_session() as db:
            db.add(
                Order(
                    order_id=order_id,
                    external_order_id="cf-test-process-partial-return",
                    platform="allegro",
                    customer_name="Jan Testowy",
                    payment_done=457,
                    delivery_method="Allegro Automat DHL BOX 24/7 (AD)",
                )
            )
            db.add(
                Return(
                    order_id=order_id,
                    status="delivered",
                    customer_name="Jan Testowy",
                    allegro_return_id="return-partial-2",
                    items_json='[{"name": "Szelki guard dla dużego psa Truelove Front Line Premium L czerwone", "quantity": 1}]',
                )
            )
            db.commit()

    monkeypatch.setattr("magazyn.services.return_refunds.settings_store.settings.ALLEGRO_ACCESS_TOKEN", "token")
    monkeypatch.setattr(
        "magazyn.services.return_refunds.allegro_api.get_customer_return",
        lambda token, return_id: (
            {
                "status": "DELIVERED",
                "items": PARTIAL_RETURN_ITEMS,
                "refund": {},
            },
            None,
        ),
    )
    monkeypatch.setattr(
        "magazyn.services.return_refunds.allegro_api.get_checkout_form",
        lambda token, external_id: (PARTIAL_CHECKOUT_FORM, None),
    )

    def fake_initiate_refund(**kwargs):
        captured.update(kwargs)
        return False, "expected failure", None

    monkeypatch.setattr("magazyn.services.return_refunds.allegro_api.initiate_refund", fake_initiate_refund)

    success, message = process_refund(order_id)

    assert success is False
    assert captured["line_items"] == [{"id": "line-red-l", "type": "QUANTITY", "quantity": 1}]


def test_initiate_refund_includes_delivery_when_requested(monkeypatch):
    captured = {}

    checkout_form = {
        "payment": {"id": "payment-1"},
        "delivery": {"cost": {"amount": "12.99", "currency": "PLN"}},
        "lineItems": [{"id": "line-1", "quantity": 1, "price": {"amount": "100.00", "currency": "PLN"}}],
    }

    class DummyResponse:
        status_code = 201

        def json(self):
            return {"id": "refund-1", "totalValue": {"amount": "112.99", "currency": "PLN"}}

    def fake_request_with_retry(method, url, *, endpoint, **kwargs):
        captured["payload"] = kwargs["json"]
        return DummyResponse()

    monkeypatch.setattr("magazyn.allegro_api.refunds.get_checkout_form", lambda access_token, order_external_id: (checkout_form, None))
    monkeypatch.setattr("magazyn.allegro_api.refunds._request_with_retry", fake_request_with_retry)

    success, message, _ = initiate_refund(
        access_token="token",
        return_id=None,
        order_external_id="order-1",
        line_items=[{"id": "line-1", "type": "QUANTITY", "quantity": 1}],
        delivery_cost_covered=True,
    )

    assert success is True
    assert captured["payload"]["delivery"]["value"]["amount"] == "12.99"


def test_check_refund_eligibility_blocks_cod_pending_settlement(app, monkeypatch):
    order_id = "allegro_test_cod_pending_settlement"

    checkout_form = {
        "summary": {"totalToPay": {"amount": "214.39", "currency": "PLN"}},
        "payment": {
            "id": "payment-cod-pending",
            "type": "CASH_ON_DELIVERY",
            "paidAmount": None,
        },
        "delivery": {"cost": {"amount": "15.39", "currency": "PLN"}},
        "lineItems": [{"id": "line-1", "quantity": 1, "price": {"amount": "199.00", "currency": "PLN"}}],
    }

    with app.app_context():
        from magazyn.db import get_session

        with get_session() as db:
            db.add(
                Order(
                    order_id=order_id,
                    external_order_id="cf-test-cod-pending",
                    platform="allegro",
                    customer_name="Jan Testowy",
                    payment_method="Pobranie",
                    payment_method_cod=True,
                    payment_done=214.39,
                )
            )
            db.add(
                Return(
                    order_id=order_id,
                    status="delivered",
                    customer_name="Jan Testowy",
                    allegro_return_id="return-cod-pending",
                    stock_restored=True,
                    items_json="[]",
                )
            )
            db.commit()

        monkeypatch.setattr("magazyn.services.return_refunds.settings_store.settings.ALLEGRO_ACCESS_TOKEN", "token")
        monkeypatch.setattr(
            "magazyn.services.return_refunds.allegro_api.get_checkout_form",
            lambda token, external_id: (checkout_form, None),
        )
        monkeypatch.setattr(
            "magazyn.services.return_refunds.allegro_api.get_cod_settlement_status",
            lambda token, checkout: ("pending", {"payment_id": "payment-cod-pending", "total_amount": 214.39, "currency": "PLN"}),
        )

        eligible, message, details = check_refund_eligibility(order_id)

    assert eligible is False
    assert "zaksiegowane" in message.lower()
    assert details["cod_settlement_pending"] is True
    assert details["allegro_status"] == "COD_PENDING_SETTLEMENT"


def test_check_refund_eligibility_allows_cod_after_settlement(app, monkeypatch):
    order_id = "allegro_test_cod_settled"

    checkout_form = {
        "summary": {"totalToPay": {"amount": "214.39", "currency": "PLN"}},
        "delivery": {"cost": {"amount": "15.39", "currency": "PLN"}},
        "lineItems": [{"id": "line-1", "quantity": 1, "price": {"amount": "199.00", "currency": "PLN"}}],
    }

    with app.app_context():
        from magazyn.db import get_session

        with get_session() as db:
            db.add(
                Order(
                    order_id=order_id,
                    external_order_id="cf-test-cod-settled",
                    platform="allegro",
                    customer_name="Jan Testowy",
                    payment_method="Pobranie",
                    payment_method_cod=True,
                    payment_done=214.39,
                )
            )
            db.add(
                Return(
                    order_id=order_id,
                    status="delivered",
                    customer_name="Jan Testowy",
                    allegro_return_id="return-cod-settled",
                    stock_restored=True,
                    items_json="[]",
                )
            )
            db.commit()

        monkeypatch.setattr("magazyn.services.return_refunds.settings_store.settings.ALLEGRO_ACCESS_TOKEN", "token")
        monkeypatch.setattr(
            "magazyn.services.return_refunds.allegro_api.get_checkout_form",
            lambda token, external_id: (checkout_form, None),
        )
        monkeypatch.setattr(
            "magazyn.services.return_refunds.allegro_api.get_cod_settlement_status",
            lambda token, checkout: ("settled", {"settled_at": "2026-07-10T10:00:00Z"}),
        )
        monkeypatch.setattr(
            "magazyn.services.return_refunds.allegro_api.get_customer_return",
            lambda token, return_id: (_ for _ in ()).throw(AssertionError("get_customer_return nie powinno byc wywolane")),
        )

        eligible, message, details = check_refund_eligibility(order_id)

    assert eligible is True
    assert "przywrocenie stanu" in message.lower()
    assert details["allegro_status"] == "STOCK_RESTORED"


def test_process_refund_blocks_cod_pending_settlement(app, monkeypatch):
    order_id = "allegro_test_process_cod_pending"

    with app.app_context():
        from magazyn.db import get_session

        with get_session() as db:
            db.add(
                Order(
                    order_id=order_id,
                    external_order_id="cf-test-process-cod-pending",
                    platform="allegro",
                    customer_name="Jan Testowy",
                    payment_method="Pobranie",
                    payment_method_cod=True,
                    payment_done=214.39,
                )
            )
            db.add(
                Return(
                    order_id=order_id,
                    status="delivered",
                    customer_name="Jan Testowy",
                    allegro_return_id="return-cod-process",
                    stock_restored=True,
                    items_json="[]",
                )
            )
            db.commit()

    monkeypatch.setattr("magazyn.services.return_refunds.settings_store.settings.ALLEGRO_ACCESS_TOKEN", "token")
    monkeypatch.setattr(
        "magazyn.services.return_refunds.allegro_api.get_checkout_form",
        lambda token, external_id: (
            {
                "payment": {"id": "payment-cod-pending", "type": "CASH_ON_DELIVERY"},
                "summary": {"totalToPay": {"amount": "214.39", "currency": "PLN"}},
            },
            None,
        ),
    )
    monkeypatch.setattr(
        "magazyn.services.return_refunds.allegro_api.get_cod_settlement_status",
        lambda token, checkout: ("pending", {"payment_id": "payment-cod-pending"}),
    )
    monkeypatch.setattr(
        "magazyn.services.return_refunds.allegro_api.initiate_refund",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("initiate_refund nie powinno byc wywolane")),
    )

    success, message = process_refund(order_id)

    assert success is False
    assert "zaksiegowane" in message.lower()