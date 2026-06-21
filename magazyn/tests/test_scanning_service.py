from magazyn.db import get_session
from magazyn.models.orders import Order, OrderProduct, OrderStatusLog
from magazyn.models.products import Product, ProductSize
from magazyn.services.scanning import (
    barcode_matches_order,
    check_and_auto_pack,
    parse_last_order_data,
)


def _create_auto_pack_order(app, *, order_id="ORD-AUTO", quantity=1):
    with app.app_context():
        with get_session() as db_session:
            product = Product(category="Szelki", brand="Truelove", series="Front Line", color="Czarny")
            db_session.add(product)
            db_session.flush()
            size = ProductSize(product_id=product.id, size="M", quantity=5, barcode=f"EAN-{order_id}")
            db_session.add(size)
            db_session.flush()
            db_session.add(Order(order_id=order_id, customer_name="Test"))
            db_session.add(
                OrderProduct(
                    order_id=order_id,
                    product_size_id=size.id,
                    name="Szelki Front Line",
                    quantity=quantity,
                )
            )
            db_session.add(OrderStatusLog(order_id=order_id, status="wydrukowano"))
            return size.id


def _latest_status(app, order_id):
    with app.app_context():
        with get_session() as db_session:
            return (
                db_session.query(OrderStatusLog)
                .filter(OrderStatusLog.order_id == order_id)
                .order_by(OrderStatusLog.id.desc())
                .first()
                .status
            )


def test_parse_last_order_data_accepts_dict_and_json():
    assert parse_last_order_data({"order_id": "1"}) == {"order_id": "1"}
    assert parse_last_order_data('{"order_id": "2"}') == {"order_id": "2"}


def test_parse_last_order_data_returns_empty_dict_for_invalid_data():
    assert parse_last_order_data("not-json") == {}
    assert parse_last_order_data(["not", "dict"]) == {}


def test_barcode_matches_order_direct_and_partial_tracking():
    order_data = {
        "package_ids": ["pkg-1"],
        "tracking_numbers": ["JJD000030123456"],
        "delivery_package_nr": "A003RFH916",
    }

    assert barcode_matches_order(order_data, "pkg-1") is True
    assert barcode_matches_order(order_data, "prefix-JJD000030123456-suffix") is True
    assert barcode_matches_order(order_data, "A003RFH916") is True
    assert barcode_matches_order(order_data, "missing") is False


def test_barcode_matches_orlen_carrier_waybill():
    order_data = {
        "package_ids": ["ship-1"],
        "tracking_numbers": ["AD02MJHDL5", "2102413302196"],
        "delivery_package_nr": "AD02MJHDL5",
    }
    assert barcode_matches_order(order_data, "2102413302196") is True


def test_barcode_matches_dhl_jjd_and_routing_from_label():
    order_a = {"tracking_numbers": ["2LPL02495+83545000"]}
    order_b = {"tracking_numbers": ["2LPL00910+83545000"]}
    assert barcode_matches_order(order_a, "2LPL02495+83545000") is True
    assert barcode_matches_order(order_b, "2LPL02495+83545000") is False
    assert barcode_matches_order(order_b, "2LPL00910+83545000") is True
    order_data = {
        "tracking_numbers": [
            "AD02MHU8Z9",
            "30774980700",
            "JJD000030230864000435460935",
            "2LPL02495+83545000",
        ],
        "delivery_package_nr": "AD02MHU8Z9",
        "package_ids": ["d988625a-39dc-44fe-8684-35f2fb0b791f"],
    }
    assert barcode_matches_order(order_data, "JJD000030230864000435460935") is True
    assert barcode_matches_order(order_data, "2LPL02495+83545000") is True
    assert barcode_matches_order(order_data, "30774980700") is True


def test_check_and_auto_pack_packs_single_product_order(app):
    product_size_id = _create_auto_pack_order(app, order_id="ORD-PACK", quantity=1)
    scan_state = {
        "last_product_scan": {
            "barcode": "EAN-ORD-PACK",
            "product_size_id": product_size_id,
            "timestamp": 100.0,
            "scan_key": "scan-1",
        },
        "last_label_scan": {"order_id": "ORD-PACK", "timestamp": 100.0},
    }

    with app.app_context():
        result = check_and_auto_pack(scan_state, now=105.0)

    assert result.status == "packed"
    assert result.flash_category == "success"
    assert "last_product_scan" not in scan_state
    assert "last_label_scan" not in scan_state
    assert "scanned_products_for_order" not in scan_state
    assert _latest_status(app, "ORD-PACK") == "spakowano"


def test_check_and_auto_pack_respects_quantity_and_ignores_duplicate_scan(app):
    product_size_id = _create_auto_pack_order(app, order_id="ORD-QTY", quantity=2)
    scan_state = {
        "last_product_scan": {
            "barcode": "EAN-ORD-QTY",
            "product_size_id": product_size_id,
            "timestamp": 200.0,
            "scan_key": "scan-1",
        },
        "last_label_scan": {"order_id": "ORD-QTY", "timestamp": 200.0},
    }

    with app.app_context():
        first_result = check_and_auto_pack(scan_state, now=205.0)
        duplicate_result = check_and_auto_pack(scan_state, now=206.0)

    assert first_result.status == "partial"
    assert duplicate_result.status == "partial"
    assert first_result.flash_message == "Zeskanowano 1/2 produktów"
    assert scan_state["scanned_products_for_order"]["ORD-QTY"]["counts"] == {str(product_size_id): 1}
    assert _latest_status(app, "ORD-QTY") == "wydrukowano"

    scan_state["last_product_scan"] = {
        "barcode": "EAN-ORD-QTY",
        "product_size_id": product_size_id,
        "timestamp": 210.0,
        "scan_key": "scan-2",
    }

    with app.app_context():
        final_result = check_and_auto_pack(scan_state, now=211.0)

    assert final_result.status == "packed"
    assert "scanned_products_for_order" not in scan_state
    assert _latest_status(app, "ORD-QTY") == "spakowano"