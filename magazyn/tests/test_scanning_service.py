from magazyn.services.scanning import barcode_matches_order, parse_last_order_data


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