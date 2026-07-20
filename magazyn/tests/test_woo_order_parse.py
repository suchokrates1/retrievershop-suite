from magazyn.woocommerce_api.orders import parse_woo_order_to_data


def test_parse_woo_order_to_data_basic():
    order = {
        "id": 42,
        "status": "processing",
        "currency": "PLN",
        "total": "199.00",
        "date_created": "2026-07-20T10:00:00",
        "date_paid": "2026-07-20T10:01:00",
        "payment_method": "bacs",
        "payment_method_title": "Przelew",
        "customer_note": "",
        "billing": {
            "first_name": "Jan",
            "last_name": "Kowalski",
            "email": "jan@example.com",
            "phone": "500100200",
            "address_1": "Ul. Test 1",
            "city": "Warszawa",
            "postcode": "00-001",
            "country": "PL",
            "company": "",
        },
        "shipping": {
            "first_name": "Jan",
            "last_name": "Kowalski",
            "address_1": "Ul. Test 1",
            "city": "Warszawa",
            "postcode": "00-001",
            "country": "PL",
        },
        "shipping_lines": [
            {"method_title": "InPost Paczkomat", "method_id": "easypack_parcel_machines", "total": "13.99"}
        ],
        "line_items": [
            {"name": "Szelki L", "sku": "5901234567890", "quantity": 1, "price": 185.01}
        ],
        "meta_data": [{"key": "_parcel_locker", "value": "WAW123A"}],
    }
    data = parse_woo_order_to_data(order)
    assert data["order_id"] == "woo_42"
    assert data["platform"] == "woocommerce"
    assert data["delivery_point_id"] == "WAW123A"
    assert data["products"][0]["ean"] == "5901234567890"
    assert data["payment_done"] == 199.0
