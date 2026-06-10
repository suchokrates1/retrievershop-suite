"""Testy dla helperow shipment management agenta drukowania."""

from magazyn.services.print_agent_shipments import (
    build_receiver,
    choose_package_dimensions,
    truncate_pickup_street,
)


def test_build_receiver_uses_pickup_point_address_for_point_delivery():
    order_data = {
        "delivery_fullname": "Beata Kornacka",
        "delivery_address": "ul. gen. Sylwestra Kaliskiego 25 lok. 47",
        "delivery_postcode": "01-476",
        "delivery_city": "Warszawa",
        "delivery_country_code": "PL",
        "delivery_point_id": "352854",
        "delivery_point_address": "Kaliskiego 39",
        "delivery_point_postcode": "01-485",
        "delivery_point_city": "Warszawa",
        "email": "buyer@allegromail.pl",
        "phone": "+48665254563",
    }

    receiver = build_receiver(order_data)

    assert receiver == {
        "name": "Beata Kornacka",
        "street": "Kaliskiego 39",
        "postalCode": "01-485",
        "city": "Warszawa",
        "countryCode": "PL",
        "email": "buyer@allegromail.pl",
        "phone": "+48665254563",
        "point": "352854",
    }


def test_choose_package_dimensions_gabaryt_a():
    dims = choose_package_dimensions([{"quantity": 2}, {"quantity": 3}])

    assert dims == {"length": 40, "width": 38, "height": 8}


def test_choose_package_dimensions_gabaryt_b():
    dims = choose_package_dimensions([{"quantity": 6}])

    assert dims == {"length": 40, "width": 38, "height": 19}


def test_build_receiver_truncates_long_pickup_point_street():
    order_data = {
        "delivery_fullname": "Monika Koleśnik",
        "delivery_address": "Andrukiewicza 11 m 36",
        "delivery_postcode": "15-204",
        "delivery_city": "Białystok",
        "delivery_country_code": "PL",
        "delivery_point_id": "AL042BI1",
        "delivery_point_address": "Piasta 140h/ Ks. Stanisława Andruszkiewicza",
        "delivery_point_postcode": "15-204",
        "delivery_point_city": "Białystok",
        "email": "buyer@allegromail.pl",
        "phone": "+48123456789",
    }

    long_street = order_data["delivery_point_address"]
    receiver = build_receiver(order_data)

    assert receiver["street"] == truncate_pickup_street(long_street)
    assert len(receiver["street"]) == 35
    assert receiver["point"] == "AL042BI1"


def test_build_receiver_uses_home_address_without_pickup_point():
    order_data = {
        "delivery_fullname": "Anna Nowak",
        "delivery_address": "Kurierska 10",
        "delivery_postcode": "00-001",
        "delivery_city": "Warszawa",
        "delivery_country_code": "PL",
        "email": "anna@test.pl",
        "phone": "700222333",
    }

    receiver = build_receiver(order_data)

    assert receiver == {
        "name": "Anna Nowak",
        "street": "Kurierska 10",
        "postalCode": "00-001",
        "city": "Warszawa",
        "countryCode": "PL",
        "email": "anna@test.pl",
        "phone": "700222333",
    }