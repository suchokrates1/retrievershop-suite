"""Testy dla refundow recznych zwrotow bez customer-return Allegro."""

from datetime import datetime, timezone

from magazyn.models.orders import Order, OrderStatusLog
from magazyn.models.returns import Return
from magazyn.services.return_refunds import check_refund_eligibility


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