"""Testy UI/API dla recznego tworzenia i obslugi zwrotow."""

from unittest.mock import patch

from magazyn.models.orders import Order, OrderStatusLog
from magazyn.models.returns import Return


def test_create_manual_return_from_order_card(app, client, login):
    order_id = "allegro_manual_return_route"

    with app.app_context():
        from magazyn.db import get_session

        with get_session() as db:
            db.add(
                Order(
                    order_id=order_id,
                    external_order_id="cf-manual-return-route",
                    platform="allegro",
                    customer_name="Jan Testowy",
                    payment_done=199,
                    delivery_method="Allegro Kurier DHL",
                )
            )
            db.add(OrderStatusLog(order_id=order_id, status="dostarczono"))
            db.commit()

    response = client.post(
        f"/order/{order_id}/create_manual_return",
        data={
            "notes": "Zwrot po terminie Allegro",
            "return_tracking_number": "RET123",
            "mark_in_transit": "true",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302

    with app.app_context():
        from magazyn.db import get_session

        with get_session() as db:
            return_record = db.query(Return).filter(Return.order_id == order_id).first()
            assert return_record is not None
            assert return_record.status == "in_transit"
            assert return_record.return_tracking_number == "RET123"
            assert "Zwrot po terminie Allegro" in (return_record.notes or "")

            return_status_log = (
                db.query(OrderStatusLog)
                .filter(
                    OrderStatusLog.order_id == order_id,
                    OrderStatusLog.status == "zwrot",
                )
                .first()
            )
            assert return_status_log is not None


def test_create_manual_return_does_not_send_correction_email(app, client, login):
    order_id = "allegro_manual_return_no_correction_email"

    with app.app_context():
        from magazyn.db import get_session

        with get_session() as db:
            db.add(
                Order(
                    order_id=order_id,
                    external_order_id="cf-manual-return-no-email",
                    platform="allegro",
                    customer_name="Jan Testowy",
                    email="jan@example.com",
                    payment_done=199,
                    delivery_method="Allegro Kurier DHL",
                )
            )
            db.add(OrderStatusLog(order_id=order_id, status="dostarczono"))
            db.commit()

    with patch("magazyn.services.email_service.send_invoice_correction") as mock_send:
        response = client.post(
            f"/order/{order_id}/create_manual_return",
            data={
                "notes": "Zwrot po terminie Allegro",
                "return_tracking_number": "RET123",
                "mark_in_transit": "true",
            },
            follow_redirects=False,
        )

    assert response.status_code == 302
    mock_send.assert_not_called()


def test_mark_manual_return_delivered(app, client, login):
    order_id = "allegro_manual_return_delivered"

    with app.app_context():
        from magazyn.db import get_session

        with get_session() as db:
            db.add(
                Order(
                    order_id=order_id,
                    external_order_id="cf-manual-return-delivered",
                    platform="allegro",
                    customer_name="Jan Testowy",
                    payment_done=199,
                    delivery_method="Allegro Kurier DHL",
                )
            )
            db.add(Return(order_id=order_id, status="pending", customer_name="Jan Testowy", items_json="[]"))
            db.commit()

    response = client.post(f"/order/{order_id}/mark_return_delivered", data={}, follow_redirects=False)

    assert response.status_code == 302

    with app.app_context():
        from magazyn.db import get_session

        with get_session() as db:
            return_record = db.query(Return).filter(Return.order_id == order_id).first()
            assert return_record is not None
            assert return_record.status == "delivered"


def test_restore_return_stock_uses_pending_delivery_override(app, client, login, monkeypatch):
    order_id = "allegro_manual_return_restore_override"
    captured = {}

    with app.app_context():
        from magazyn.db import get_session

        with get_session() as db:
            db.add(
                Order(
                    order_id=order_id,
                    external_order_id="cf-manual-return-restore-override",
                    platform="allegro",
                    customer_name="Jan Testowy",
                    payment_done=199,
                    delivery_method="Allegro Kurier DHL",
                )
            )
            db.add(Return(order_id=order_id, status="pending", customer_name="Jan Testowy", items_json="[]"))
            db.commit()

    def fake_restore_stock(return_id, *, accept_pending_as_delivered=False, **_kwargs):
        captured["return_id"] = return_id
        captured["accept_pending_as_delivered"] = accept_pending_as_delivered
        return True

    monkeypatch.setattr(
        "magazyn.services.order_return_actions.restore_stock_for_return",
        fake_restore_stock,
    )

    response = client.post(f"/order/{order_id}/restore_return_stock", data={}, follow_redirects=False)

    assert response.status_code == 302
    assert captured["accept_pending_as_delivered"] is True