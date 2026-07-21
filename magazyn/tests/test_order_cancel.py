"""Testy anulowania zamowienia z karty."""

from decimal import Decimal
from unittest.mock import patch

from magazyn.db import get_session
from magazyn.models.orders import Order, OrderProduct, OrderStatusLog
from magazyn.models.products import Product, ProductSize, Sale
from magazyn.services.order_cancel import cancel_order, can_cancel_order


def test_can_cancel_order_status_gate():
    assert can_cancel_order("pobrano")
    assert can_cancel_order("spakowano")
    assert can_cancel_order("blad_druku")
    assert not can_cancel_order("wyslano")
    assert not can_cancel_order("dostarczono")
    assert not can_cancel_order("anulowano")


def test_cancel_blocked_after_spakowano(app):
    order_id = "cancel_blocked_wyslano"
    with app.app_context():
        with get_session() as db:
            db.add(Order(order_id=order_id, platform="allegro", external_order_id="cf-1"))
            db.add(OrderStatusLog(order_id=order_id, status="wyslano"))
            db.commit()

        result = cancel_order(order_id, money_already_refunded=True)
        assert result.category == "error"
        assert "niedostepne" in result.message


def test_cancel_skips_refund_when_money_already_refunded(app):
    order_id = "cancel_money_done"
    with app.app_context():
        with get_session() as db:
            db.add(
                Order(
                    order_id=order_id,
                    platform="allegro",
                    external_order_id="cf-cancel-done",
                    payment_done=Decimal("100.00"),
                )
            )
            db.add(OrderStatusLog(order_id=order_id, status="pobrano"))
            db.commit()

        with patch(
            "magazyn.services.order_cancel.process_cancel_refund"
        ) as refund_mock, patch(
            "magazyn.allegro_api.fulfillment.update_fulfillment_status"
        ) as fulfill_mock, patch(
            "magazyn.services.invoice_service.generate_correction_invoice"
        ) as corr_mock:
            corr_mock.return_value = {"success": True, "invoice_number": None, "errors": []}
            result = cancel_order(
                order_id,
                money_already_refunded=True,
                reason="Brak XL czerwona",
            )

        refund_mock.assert_not_called()
        fulfill_mock.assert_called_once_with("cf-cancel-done", "CANCELLED")
        assert result.category in ("success", "warning")
        assert "anulowane" in result.message.lower() or "Anulowane" in result.message

        with get_session() as db:
            status = (
                db.query(OrderStatusLog)
                .filter(OrderStatusLog.order_id == order_id)
                .order_by(OrderStatusLog.id.desc())
                .first()
            )
            assert status.status == "anulowano"
            assert "pieniadze juz zwrocone" in (status.notes or "")


def test_cancel_restores_stock_from_sale(app):
    order_id = "cancel_restore_stock"
    with app.app_context():
        with get_session() as db:
            product = Product(
                category="Obroza",
                brand="Truelove",
                series="Active",
                color="czerwona",
            )
            db.add(product)
            db.flush()
            ps = ProductSize(
                product_id=product.id,
                size="XL",
                quantity=0,
                barcode="EAN-CANCEL-1",
                stock_value=Decimal("0"),
            )
            db.add(ps)
            db.flush()
            db.add(
                Order(
                    order_id=order_id,
                    platform="allegro",
                    external_order_id="cf-restore",
                    payment_done=Decimal("80.00"),
                )
            )
            db.add(
                OrderProduct(
                    order_id=order_id,
                    name="Obroza Active XL czerwona",
                    quantity=1,
                    price_brutto=Decimal("80.00"),
                    ean="EAN-CANCEL-1",
                    product_size_id=ps.id,
                )
            )
            db.add(OrderStatusLog(order_id=order_id, status="wydrukowano"))
            db.add(
                Sale(
                    product_id=product.id,
                    size="XL",
                    quantity=1,
                    sale_date="2026-07-21",
                    purchase_cost=Decimal("30.00"),
                    sale_price=Decimal("80.00"),
                    order_id=order_id,
                )
            )
            db.commit()
            ps_id = ps.id

        with patch(
            "magazyn.allegro_api.fulfillment.update_fulfillment_status"
        ), patch(
            "magazyn.services.invoice_service.generate_correction_invoice",
            return_value={"success": True, "invoice_number": None, "errors": []},
        ):
            result = cancel_order(order_id, money_already_refunded=True)

        assert result.category in ("success", "warning")
        assert result.details.get("restored")

        with get_session() as db:
            ps = db.query(ProductSize).filter(ProductSize.id == ps_id).first()
            assert ps.quantity == 1
            sale = db.query(Sale).filter(Sale.order_id == order_id).first()
            assert sale.quantity_returned == 1


def test_cancel_route_money_already_refunded(app, client, login):
    order_id = "cancel_route_1"
    with app.app_context():
        with get_session() as db:
            db.add(
                Order(
                    order_id=order_id,
                    platform="allegro",
                    external_order_id="cf-route",
                )
            )
            db.add(OrderStatusLog(order_id=order_id, status="spakowano"))
            db.commit()

        with patch(
            "magazyn.allegro_api.fulfillment.update_fulfillment_status"
        ) as fulfill_mock, patch(
            "magazyn.services.invoice_service.generate_correction_invoice",
            return_value={"success": True, "invoice_number": None, "errors": []},
        ):
            response = client.post(
                f"/order/{order_id}/cancel",
                data={
                    "money_already_refunded": "true",
                    "reason": "Brak produktu",
                },
                follow_redirects=False,
            )

        assert response.status_code == 302
        fulfill_mock.assert_called_once()

        with get_session() as db:
            status = (
                db.query(OrderStatusLog)
                .filter(
                    OrderStatusLog.order_id == order_id,
                    OrderStatusLog.status == "anulowano",
                )
                .first()
            )
            assert status is not None
