from magazyn.inpost_api.shipx import _normalize_pl_phone, build_shipment_payload


def test_normalize_pl_phone_strips_country_code():
    assert _normalize_pl_phone("+48 502 533 332") == "502533332"
    assert _normalize_pl_phone("48502533332") == "502533332"


def test_build_shipment_payload_locker():
    payload = build_shipment_payload(
        {
            "order_id": "woo_1",
            "delivery_fullname": "Anna Nowak",
            "email": "a@example.com",
            "phone": "500100200",
            "delivery_point_id": "WAW01A",
            "delivery_method": "InPost Paczkomat",
            "payment_method_cod": "0",
            "payment_done": 100,
        }
    )
    assert payload["service"] == "inpost_locker_standard"
    assert payload["custom_attributes"]["target_point"] == "WAW01A"
    assert payload["custom_attributes"]["sending_method"] == "parcel_locker"
    assert "cod" not in payload


def test_build_shipment_payload_courier_from_shipping_key():
    payload = build_shipment_payload(
        {
            "order_id": "woo_2",
            "customer": "Jan Kowalski",
            "shipping": "Kurier InPost",
            "delivery_address": "Testowa 1",
            "delivery_city": "Krakow",
            "delivery_postcode": "30-001",
            "delivery_country_code": "PL",
            "email": "j@example.com",
            "phone": "501501501",
            "payment_method_cod": "1",
            "payment_done": 55.5,
        }
    )
    assert payload["service"] == "inpost_courier_c2c"
    assert payload["receiver"]["address"]["city"] == "Krakow"
    assert payload["custom_attributes"]["sending_method"] == "parcel_locker"
    assert payload["cod"]["amount"] == 55.5
