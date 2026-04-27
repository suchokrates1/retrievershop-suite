from magazyn.db import get_session
from magazyn.models.orders import OrderProduct, OrderStatusLog


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
    from magazyn.services.order_sync import sync_order_from_data

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
    from magazyn.services.order_sync import sync_order_from_data

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


def test_sync_order_from_data_merges_duplicate_products(app):
    from magazyn.services.order_sync import sync_order_from_data

    order_id = "allegro_cf-dup-products-1"
    order_data = {
        "order_id": order_id,
        "external_order_id": "cf-dup-products-1",
        "platform": "allegro",
        "email": "test@example.com",
        "delivery_fullname": "Test User",
        "date_add": 1700000000,
        "payment_method_cod": False,
        "payment_done": 10,
        "_allegro_status": "READY_FOR_PROCESSING",
        "_allegro_fulfillment_status": "NEW",
        "products": [
            {
                "name": "Szelki L czarne",
                "quantity": 1,
                "price_brutto": "207.00",
                "auction_id": "18167082745",
                "sku": "SKU-1",
                "ean": "",
            },
            {
                "name": "Szelki L czarne",
                "quantity": 1,
                "price_brutto": "207.00",
                "auction_id": "18167082745",
                "sku": "SKU-1",
                "ean": "",
            },
        ],
    }

    with app.app_context():
        with get_session() as db:
            sync_order_from_data(db, order_data)
            db.commit()

        with get_session() as db:
            products = (
                db.query(OrderProduct)
                .filter(OrderProduct.order_id == order_id)
                .all()
            )

    assert len(products) == 1
    assert products[0].quantity == 2