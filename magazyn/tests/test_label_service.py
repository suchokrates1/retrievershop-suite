"""Testy dla magazyn.services.label_service."""

import pytest
from unittest.mock import patch

from magazyn.services.label_service import (
    AllegroLabelService,
    _load_sender_data,
    _build_receiver,
    _find_delivery_service_id,
    _default_packages,
    _wait_for_confirmation,
)


# --------------- helpers ---------------

SAMPLE_ORDER_DATA = {
    "delivery": {
        "method": {"name": "Allegro Paczkomaty InPost 24/7"},
        "address": {
            "firstName": "Jan",
            "lastName": "Kowalski",
            "street": "Testowa 5",
            "city": "Krakow",
            "zipCode": "30-001",
            "countryCode": "PL",
            "phoneNumber": "600111222",
        },
        "pickupPoint": {"id": "KRA123"},
    },
    "buyer": {
        "email": "jan@test.pl",
        "phoneNumber": "600111222",
    },
}

SAMPLE_ORDER_NO_PICKUP = {
    "delivery": {
        "method": {"name": "Allegro Kurier DPD"},
        "address": {
            "firstName": "Anna",
            "lastName": "Nowak",
            "street": "Kurierska 10",
            "city": "Warszawa",
            "zipCode": "00-001",
            "countryCode": "PL",
        },
    },
    "buyer": {
        "email": "anna@test.pl",
        "phoneNumber": "700222333",
    },
}


# --------------- _build_receiver ---------------

def test_build_receiver_with_pickup():
    receiver = _build_receiver(SAMPLE_ORDER_DATA)

    assert receiver["name"] == "Jan Kowalski"
    assert receiver["street"] == "Testowa 5"
    assert receiver["city"] == "Krakow"
    assert receiver["zipCode"] == "30-001"
    assert receiver["pickupPointId"] == "KRA123"
    assert receiver["phone"] == "600111222"
    assert receiver["email"] == "jan@test.pl"


def test_build_receiver_no_pickup():
    receiver = _build_receiver(SAMPLE_ORDER_NO_PICKUP)

    assert receiver["name"] == "Anna Nowak"
    assert "pickupPointId" not in receiver
    assert receiver["phone"] == "700222333"


def test_build_receiver_empty_order():
    receiver = _build_receiver({})

    assert receiver["name"] == ""
    assert receiver["countryCode"] == "PL"


# --------------- _load_sender_data ---------------

@patch("magazyn.services.label_service.settings_store")
def test_load_sender_data(mock_store):
    mock_store.get.side_effect = lambda k: {
        "SENDER_NAME": "Retriever Shop",
        "SENDER_STREET": "Testowa 1",
        "SENDER_CITY": "Poznan",
        "SENDER_ZIPCODE": "60-001",
        "SENDER_COUNTRY_CODE": "PL",
        "SENDER_PHONE": "500000000",
        "SENDER_EMAIL": "sklep@test.pl",
    }.get(k)

    result = _load_sender_data()

    assert result["name"] == "Retriever Shop"
    assert result["city"] == "Poznan"
    assert result["zipCode"] == "60-001"


@patch("magazyn.services.label_service.settings_store")
def test_load_sender_data_defaults(mock_store):
    mock_store.get.return_value = None

    result = _load_sender_data()

    assert result["name"] == "Retriever Shop"
    assert result["countryCode"] == "PL"


# --------------- _find_delivery_service_id ---------------

@patch("magazyn.services.label_service.get_delivery_services")
def test_find_delivery_service_exact_match(mock_services):
    mock_services.return_value = [
        {"id": "svc-inpost", "name": "Allegro Paczkomaty InPost 24/7"},
        {"id": "svc-dpd", "name": "Allegro Kurier DPD"},
    ]

    result = _find_delivery_service_id("Allegro Paczkomaty InPost 24/7")

    assert result == "svc-inpost"


@patch("magazyn.services.label_service.get_delivery_services")
def test_find_delivery_service_partial_match(mock_services):
    mock_services.return_value = [
        {"id": "svc-dpd", "name": "Allegro Kurier DPD Standard"},
    ]

    result = _find_delivery_service_id("Allegro Kurier DPD")

    assert result == "svc-dpd"


@patch("magazyn.services.label_service.get_delivery_services")
def test_find_delivery_service_not_found(mock_services):
    mock_services.return_value = [
        {"id": "svc-dpd", "name": "Allegro Kurier DPD"},
    ]

    result = _find_delivery_service_id("Odbiór osobisty")

    assert result is None


def test_find_delivery_service_empty_name():
    result = _find_delivery_service_id("")

    assert result is None


# --------------- _default_packages ---------------

def test_default_packages():
    pkgs = _default_packages()

    assert len(pkgs) == 1
    assert pkgs[0]["weight"]["value"] == 1.0
    assert pkgs[0]["weight"]["unit"] == "KILOGRAM"


# --------------- _wait_for_confirmation ---------------

@patch("magazyn.services.label_service.get_shipment_details")
@patch("magazyn.services.label_service.time.sleep")
def test_wait_for_confirmation_immediate(mock_sleep, mock_details):
    mock_details.return_value = {
        "status": "CONFIRMED",
        "packages": [{"waybill": "WB123"}],
    }

    result = _wait_for_confirmation("ship-1")

    assert result["status"] == "CONFIRMED"
    mock_sleep.assert_not_called()


@patch("magazyn.services.label_service.get_shipment_details")
@patch("magazyn.services.label_service.time.sleep")
def test_wait_for_confirmation_after_draft(mock_sleep, mock_details):
    mock_details.side_effect = [
        {"status": "DRAFT"},
        {"status": "CONFIRMED", "packages": [{"waybill": "WB456"}]},
    ]

    result = _wait_for_confirmation("ship-1")

    assert result["status"] == "CONFIRMED"
    mock_sleep.assert_called_once()


@patch("magazyn.services.label_service.get_shipment_details")
@patch("magazyn.services.label_service.time.sleep")
def test_wait_for_confirmation_cancelled(mock_sleep, mock_details):
    mock_details.return_value = {"status": "CANCELLED"}

    with pytest.raises(RuntimeError, match="anulowana"):
        _wait_for_confirmation("ship-1")


@patch("magazyn.services.label_service.get_shipment_details")
@patch("magazyn.services.label_service.time.sleep")
@patch("magazyn.services.label_service._MAX_WAIT_SECONDS", 4)
@patch("magazyn.services.label_service._POLL_INTERVAL", 2)
def test_wait_for_confirmation_timeout(mock_sleep, mock_details):
    mock_details.return_value = {"status": "DRAFT"}

    with pytest.raises(RuntimeError, match="nie zostala potwierdzona"):
        _wait_for_confirmation("ship-1")


# --------------- AllegroLabelService.create_and_get_label ---------------

@patch("magazyn.services.label_service.resolve_carrier_id", return_value="INPOST")
@patch("magazyn.services.label_service.get_shipment_label", return_value=b"pdf-data")
@patch("magazyn.services.label_service._wait_for_confirmation")
@patch("magazyn.services.label_service.create_shipment")
@patch("magazyn.services.label_service._load_sender_data")
@patch("magazyn.services.label_service._find_delivery_service_id", return_value="svc-inpost")
def test_create_and_get_label_success(
    mock_find, mock_sender, mock_create, mock_wait, mock_label, mock_carrier
):
    mock_sender.return_value = {"name": "Retriever Shop"}
    mock_create.return_value = {"id": "ship-abc"}
    mock_wait.return_value = {
        "status": "CONFIRMED",
        "packages": [{"waybill": "WB999"}],
    }

    svc = AllegroLabelService()
    result = svc.create_and_get_label(
        checkout_form_id="order-123",
        order_data=SAMPLE_ORDER_DATA,
    )

    assert result["shipment_id"] == "ship-abc"
    assert result["waybill"] == "WB999"
    assert result["carrier_id"] == "INPOST"
    assert result["label_data"] == b"pdf-data"
    assert result["label_format"] == "PDF"


@patch("magazyn.services.label_service._find_delivery_service_id", return_value=None)
def test_create_and_get_label_no_service(mock_find):
    svc = AllegroLabelService()

    with pytest.raises(RuntimeError, match="Nie znaleziono uslugi dostawy"):
        svc.create_and_get_label(
            checkout_form_id="order-123",
            order_data=SAMPLE_ORDER_DATA,
        )


# --------------- AllegroLabelService.register_tracking ---------------

@patch("magazyn.services.label_service.add_shipment_tracking")
def test_register_tracking(mock_add):
    mock_add.return_value = {"id": "tracking-1"}

    svc = AllegroLabelService()
    result = svc.register_tracking(
        checkout_form_id="order-123",
        carrier_id="INPOST",
        waybill="WB999",
    )

    assert result == {"id": "tracking-1"}
    mock_add.assert_called_once_with(
        "order-123", carrier_id="INPOST", waybill="WB999",
    )


# --------------- AllegroLabelService.cancel ---------------

@patch("magazyn.services.label_service.cancel_shipment")
def test_cancel(mock_cancel):
    mock_cancel.return_value = {"cancelled": ["ship-1"]}

    svc = AllegroLabelService()
    result = svc.cancel("ship-1")

    assert result["cancelled"] == ["ship-1"]
    mock_cancel.assert_called_once_with(["ship-1"])
