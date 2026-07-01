from decimal import Decimal

from sqlalchemy import desc

from magazyn.db import get_session
from magazyn.models.orders import Order, OrderStatusLog
from magazyn.services.manual_order_actions import apply_manual_tracking, finalize_manual_order_creation
from magazyn.services.order_status import add_order_status
from magazyn.services.print_agent_orders import collect_printable_orders


def test_collect_printable_orders_skips_manual_orders(app):
    with app.app_context():
        with get_session() as db:
            manual = Order(
                order_id="manual_test_skip",
                platform="olx",
                date_add=9999999999,
                payment_done=Decimal("100.00"),
            )
            allegro = Order(
                order_id="allegro_test_include",
                platform="allegro",
                date_add=9999999999,
                payment_done=Decimal("100.00"),
            )
            db.add_all([manual, allegro])
            db.flush()
            add_order_status(db, manual.order_id, "pobrano", send_email=False)
            add_order_status(db, allegro.order_id, "pobrano", send_email=False)
            db.commit()

        order_ids = {item["order_id"] for item in collect_printable_orders(days=3650)}

        assert "manual_test_skip" not in order_ids
        assert "allegro_test_include" in order_ids


def test_finalize_manual_order_with_tracking_sets_wydrukowano(app):
    with app.app_context():
        with get_session() as db:
            order = Order(
                order_id="manual_test_tracking",
                platform="olx",
                date_add=1,
                payment_done=Decimal("200.00"),
                delivery_method="Kurier InPost",
                products_json='[{"name": "Test", "price_brutto": 200.0, "quantity": 1, "commission_fee": 15.0}]',
            )
            db.add(order)
            db.flush()

            finalize_manual_order_creation(
                db,
                order,
                {
                    "platform": "olx",
                    "delivery_package_nr": "620999681824160672994529",
                },
            )
            db.commit()

            saved = db.query(Order).filter(Order.order_id == "manual_test_tracking").first()
            latest = (
                db.query(OrderStatusLog)
                .filter(OrderStatusLog.order_id == "manual_test_tracking")
                .order_by(desc(OrderStatusLog.timestamp), desc(OrderStatusLog.id))
                .first()
            )

        assert saved.delivery_package_nr == "620999681824160672994529"
        assert saved.courier_code == "INPOST"
        assert latest.status == "wydrukowano"


def test_apply_manual_tracking_updates_existing_order(app):
    with app.app_context():
        with get_session() as db:
            order = Order(
                order_id="manual_test_update_tracking",
                platform="olx",
                date_add=1,
                payment_done=Decimal("100.00"),
                delivery_method="Kurier InPost",
                products_json='[{"name": "Test", "price_brutto": 100.0, "quantity": 1, "commission_fee": 7.5}]',
            )
            db.add(order)
            db.flush()
            add_order_status(db, order.order_id, "pobrano", send_email=False)

            apply_manual_tracking(db, order, "TRACK123456")
            db.commit()

            saved = db.query(Order).filter(Order.order_id == "manual_test_update_tracking").first()
            latest = (
                db.query(OrderStatusLog)
                .filter(OrderStatusLog.order_id == "manual_test_update_tracking")
                .order_by(desc(OrderStatusLog.timestamp), desc(OrderStatusLog.id))
                .first()
            )

        assert saved.delivery_package_nr == "TRACK123456"
        assert latest.status == "wydrukowano"
