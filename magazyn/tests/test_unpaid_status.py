from magazyn.db import get_session
from magazyn.models import OrderStatusLog


def test_get_allegro_internal_status_returns_unpaid_for_unconfirmed_online_order():
    from magazyn.allegro_api.orders import get_allegro_internal_status

    status = get_allegro_internal_status(
        {
            "payment_method_cod": False,
            "payment_done": 0,
            "date_confirmed": None,
            "_allegro_status": "BOUGHT",
            "_allegro_fulfillment_status": "NEW",
        }
    )

    assert status == "nieoplacone"


def test_sync_order_from_data_sets_unpaid_initial_status(app):
    from magazyn.orders import sync_order_from_data

    order_data = {
        "order_id": "allegro_cf-unpaid-1",
        "external_order_id": "cf-unpaid-1",
        "platform": "allegro",
        "email": "test@example.com",
        "delivery_fullname": "Test User",
        "date_add": 1700000000,
        "payment_method_cod": False,
        "payment_done": 0,
        "_allegro_status": "BOUGHT",
        "_allegro_fulfillment_status": "NEW",
    }

    with app.app_context():
        with get_session() as db:
            sync_order_from_data(db, order_data)
            db.commit()

        with get_session() as db:
            status_log = (
                db.query(OrderStatusLog)
                .filter(OrderStatusLog.order_id == "allegro_cf-unpaid-1")
                .first()
            )

    assert status_log is not None
    assert status_log.status == "nieoplacone"


def test_sync_order_from_data_sets_pobrano_for_cod_order(app):
    from magazyn.orders import sync_order_from_data

    order_data = {
        "order_id": "allegro_cf-cod-1",
        "external_order_id": "cf-cod-1",
        "platform": "allegro",
        "email": "test@example.com",
        "delivery_fullname": "Test User",
        "date_add": 1700000000,
        "payment_method_cod": True,
        "payment_done": 0,
        "_allegro_status": "BOUGHT",
        "_allegro_fulfillment_status": "NEW",
    }

    with app.app_context():
        with get_session() as db:
            sync_order_from_data(db, order_data)
            db.commit()

        with get_session() as db:
            status_log = (
                db.query(OrderStatusLog)
                .filter(OrderStatusLog.order_id == "allegro_cf-cod-1")
                .first()
            )

    assert status_log is not None
    assert status_log.status == "pobrano"