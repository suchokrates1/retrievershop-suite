"""Testy anulacji przed wysylka → zwrot jako odebrany."""

from __future__ import annotations

from magazyn.domain.returns import NEVER_SHIPPED_DELIVERED_NOTE, RETURN_STATUS_DELIVERED
from magazyn.db import get_session
from magazyn.models.orders import Order, OrderStatusLog
from magazyn.models.returns import Return, ReturnStatusLog
from magazyn.services.return_core import (
    order_package_never_shipped,
    promote_never_shipped_return_to_delivered,
)


def test_order_never_shipped_when_only_warehouse_statuses(app):
    with app.app_context():
        with get_session() as db:
            db.add(
                Order(
                    order_id="ord_never_1",
                    external_order_id="ext1",
                    customer_name="Test",
                    platform="allegro",
                )
            )
            db.flush()
            db.add(OrderStatusLog(order_id="ord_never_1", status="pobrano"))
            db.add(OrderStatusLog(order_id="ord_never_1", status="wydrukowano"))
            db.flush()
            assert order_package_never_shipped(db, "ord_never_1") is True


def test_order_shipped_when_wyslano_present(app):
    with app.app_context():
        with get_session() as db:
            db.add(
                Order(
                    order_id="ord_ship_1",
                    external_order_id="ext2",
                    customer_name="Test",
                    platform="allegro",
                )
            )
            db.flush()
            db.add(OrderStatusLog(order_id="ord_ship_1", status="pobrano"))
            db.add(OrderStatusLog(order_id="ord_ship_1", status="wyslano"))
            db.flush()
            assert order_package_never_shipped(db, "ord_ship_1") is False


def test_promote_never_shipped_return_to_delivered(app):
    with app.app_context():
        with get_session() as db:
            db.add(
                Order(
                    order_id="ord_ret_ns",
                    external_order_id="ext3",
                    customer_name="Test",
                    platform="allegro",
                )
            )
            db.flush()
            db.add(OrderStatusLog(order_id="ord_ret_ns", status="wydrukowano"))
            ret = Return(
                order_id="ord_ret_ns",
                status="pending",
                allegro_return_id="ret-1",
            )
            db.add(ret)
            db.flush()
            assert promote_never_shipped_return_to_delivered(db, ret) is True
            assert ret.status == RETURN_STATUS_DELIVERED
            db.flush()
            logs = (
                db.query(ReturnStatusLog)
                .filter(ReturnStatusLog.return_id == ret.id)
                .all()
            )
            assert any(NEVER_SHIPPED_DELIVERED_NOTE in (log.notes or "") for log in logs)
