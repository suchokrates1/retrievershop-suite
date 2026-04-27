"""Testy dla magazyn.allegro_api.shipment_management."""

import pytest
from unittest.mock import patch, MagicMock

from magazyn.allegro_api.shipment_management import (
    get_delivery_services,
    create_shipment,
    get_create_command_status,
    wait_for_shipment_creation,
    get_shipment_details,
    get_shipment_label,
    cancel_shipment,
    get_cancel_command_status,
    invalidate_delivery_services_cache,
)
from magazyn.services.print_agent_config import calculate_cod_amount


# --------------- helpers ---------------

def _mock_response(json_data=None, status_code=200, content=b""):
    resp = MagicMock()
    resp.json.return_value = json_data or {}
    resp.status_code = status_code
    resp.content = content
    return resp


def _mock_error_response(status_code):
    resp = MagicMock()
    resp.status_code = status_code
    exc = Exception("HTTP error")
    exc.response = resp
    return exc


SAMPLE_SENDER = {
    "name": "Retriever Shop",
    "street": "Testowa 1",
    "postalCode": "00-001",
    "city": "Warszawa",
    "countryCode": "PL",
    "phone": "500000000",
    "email": "test@test.pl",
}

SAMPLE_RECEIVER = {
    "name": "Jan Kowalski",
    "street": "Odbiorcza 2",
    "postalCode": "30-001",
    "city": "Krakow",
    "countryCode": "PL",
    "phone": "600000000",
    "email": "jan@test.pl",
}

SAMPLE_PACKAGES = [
    {
        "type": "OTHER",
        "weight": {"value": 1.0, "unit": "KILOGRAMS"},
        "length": {"value": 30, "unit": "CENTIMETER"},
        "width": {"value": 20, "unit": "CENTIMETER"},
        "height": {"value": 10, "unit": "CENTIMETER"},
    }
]


# --------------- get_delivery_services ---------------

@patch("magazyn.allegro_api.shipment_management._call_with_refresh")
def test_get_delivery_services(mock_call):
    invalidate_delivery_services_cache()
    services = [{"id": {"deliveryMethodId": "svc-1", "credentialsId": None}, "name": "InPost Paczkomaty"}]
    mock_call.return_value = _mock_response({"services": services})

    result = get_delivery_services()

    assert result == services
    mock_call.assert_called_once()


@patch("magazyn.allegro_api.shipment_management._call_with_refresh")
def test_get_delivery_services_cached(mock_call):
    invalidate_delivery_services_cache()
    services = [{"id": {"deliveryMethodId": "svc-1", "credentialsId": None}, "name": "DPD"}]
    mock_call.return_value = _mock_response({"services": services})

    result1 = get_delivery_services()
    result2 = get_delivery_services()

    assert result1 == result2
    assert mock_call.call_count == 1  # drugie wywolanie z cache


@patch("magazyn.allegro_api.shipment_management._call_with_refresh")
def test_get_delivery_services_list_fallback(mock_call):
    """Gdy API zwraca liste zamiast obiektu z kluczem services."""
    invalidate_delivery_services_cache()
    services = [{"id": {"deliveryMethodId": "svc-1", "credentialsId": None}, "name": "DHL"}]
    mock_call.return_value = _mock_response(services)

    result = get_delivery_services()

    assert result == services


def test_invalidate_cache():
    invalidate_delivery_services_cache()


# --------------- create_shipment ---------------

@patch("magazyn.allegro_api.shipment_management._call_with_refresh")
def test_create_shipment(mock_call):
    mock_call.return_value = _mock_response({
        "commandId": "cmd-123",
        "input": {"deliveryMethodId": "svc-1"},
    })

    result = create_shipment(
        delivery_method_id="svc-1",
        sender=SAMPLE_SENDER,
        receiver=SAMPLE_RECEIVER,
        packages=SAMPLE_PACKAGES,
    )

    assert result["commandId"] == "cmd-123"
    body = mock_call.call_args.kwargs["json"]
    assert body["input"]["deliveryMethodId"] == "svc-1"
    assert body["input"]["sender"] == SAMPLE_SENDER
    assert body["input"]["receiver"] == SAMPLE_RECEIVER
    assert body["input"]["packages"] == SAMPLE_PACKAGES
    assert "commandId" in body


@patch("magazyn.allegro_api.shipment_management._call_with_refresh")
def test_create_shipment_with_reference(mock_call):
    mock_call.return_value = _mock_response({"commandId": "cmd-456"})

    create_shipment(
        delivery_method_id="svc-1",
        sender=SAMPLE_SENDER,
        receiver=SAMPLE_RECEIVER,
        packages=SAMPLE_PACKAGES,
        reference_number="Buty Nike Air x2",
    )

    body = mock_call.call_args.kwargs["json"]
    assert body["input"]["referenceNumber"] == "Buty Nike Air x2"


@patch("magazyn.allegro_api.shipment_management._call_with_refresh")
def test_create_shipment_with_inpost_props(mock_call):
    mock_call.return_value = _mock_response({"commandId": "cmd-789"})

    create_shipment(
        delivery_method_id="svc-1",
        sender=SAMPLE_SENDER,
        receiver=SAMPLE_RECEIVER,
        packages=SAMPLE_PACKAGES,
        additional_properties={"inpost#sendingMethod": "parcel_locker"},
    )

    body = mock_call.call_args.kwargs["json"]
    assert body["input"]["additionalProperties"] == {"inpost#sendingMethod": "parcel_locker"}


@patch("magazyn.allegro_api.shipment_management._call_with_refresh")
def test_create_shipment_with_cash_on_delivery(mock_call):
    mock_call.return_value = _mock_response({"commandId": "cmd-cod"})

    create_shipment(
        delivery_method_id="svc-1",
        sender=SAMPLE_SENDER,
        receiver=SAMPLE_RECEIVER,
        packages=SAMPLE_PACKAGES,
        cash_on_delivery={"amount": "216.99", "currency": "PLN"},
    )

    body = mock_call.call_args.kwargs["json"]
    assert body["input"]["cashOnDelivery"] == {"amount": "216.99", "currency": "PLN"}


def test_calculate_cod_amount_includes_delivery_price():
    order_data = {
        "products": [
            {"price_brutto": "207.00", "quantity": 1},
            {"price_brutto": "10.00", "quantity": 2},
        ],
        "delivery_price": "12.99",
    }

    result = calculate_cod_amount(order_data)

    assert str(result) == "239.99"


# --------------- get_create_command_status ---------------

@patch("magazyn.allegro_api.shipment_management._call_with_refresh")
def test_get_create_command_status(mock_call):
    mock_call.return_value = _mock_response({
        "commandId": "cmd-123",
        "status": "SUCCESS",
        "shipmentId": "ship-abc",
        "errors": [],
    })

    result = get_create_command_status("cmd-123")

    assert result["status"] == "SUCCESS"
    assert result["shipmentId"] == "ship-abc"


# --------------- wait_for_shipment_creation ---------------

@patch("magazyn.allegro_api.shipment_management.get_create_command_status")
def test_wait_for_shipment_creation_success(mock_status):
    mock_status.return_value = {
        "commandId": "cmd-123",
        "status": "SUCCESS",
        "shipmentId": "ship-abc",
        "errors": [],
    }

    result = wait_for_shipment_creation("cmd-123")

    assert result["shipmentId"] == "ship-abc"


@patch("magazyn.allegro_api.shipment_management.get_create_command_status")
def test_wait_for_shipment_creation_error(mock_status):
    mock_status.return_value = {
        "commandId": "cmd-123",
        "status": "ERROR",
        "errors": [{"code": "VALIDATION_ERROR", "message": "Brak numeru budynku"}],
        "shipmentId": None,
    }

    with pytest.raises(RuntimeError, match="Brak numeru budynku"):
        wait_for_shipment_creation("cmd-123")


@patch("magazyn.allegro_api.shipment_management.time")
@patch("magazyn.allegro_api.shipment_management.get_create_command_status")
def test_wait_for_shipment_creation_timeout(mock_status, mock_time):
    mock_status.return_value = {
        "commandId": "cmd-123",
        "status": "IN_PROGRESS",
        "errors": [],
        "shipmentId": None,
    }
    # Symuluj uplyw czasu: monotonic() zwraca 0, potem 31 (przekroczony timeout=30)
    mock_time.monotonic.side_effect = [0, 31]
    mock_time.sleep = MagicMock()

    with pytest.raises(TimeoutError, match="Timeout"):
        wait_for_shipment_creation("cmd-123", timeout=30.0)


# --------------- get_shipment_details ---------------

@patch("magazyn.allegro_api.shipment_management._call_with_refresh")
def test_get_shipment_details(mock_call):
    mock_call.return_value = _mock_response({
        "id": "ship-123",
        "status": "CONFIRMED",
        "packages": [{"waybill": "WB123"}],
    })

    result = get_shipment_details("ship-123")

    assert result["status"] == "CONFIRMED"
    assert result["packages"][0]["waybill"] == "WB123"


# --------------- get_shipment_label ---------------

@patch("magazyn.allegro_api.shipment_management._call_with_refresh")
def test_get_shipment_label_pdf(mock_call):
    pdf_bytes = b"%PDF-1.4 test label data"
    mock_call.return_value = _mock_response(content=pdf_bytes)
    mock_call.return_value.content = pdf_bytes

    result = get_shipment_label(["ship-123"])

    assert result == pdf_bytes
    body = mock_call.call_args.kwargs["json"]
    assert body["shipmentIds"] == ["ship-123"]
    assert body["pageSize"] == "A4"
    assert body["cutLine"] is True
    # Sprawdz ze uzywa accept_octet
    assert mock_call.call_args.kwargs.get("accept_octet") is True


@patch("magazyn.allegro_api.shipment_management._call_with_refresh")
def test_get_shipment_label_multiple(mock_call):
    """Mozna pobrac etykiety dla wielu przesylek naraz."""
    pdf_bytes = b"%PDF multi"
    mock_call.return_value = _mock_response(content=pdf_bytes)
    mock_call.return_value.content = pdf_bytes

    get_shipment_label(["ship-1", "ship-2"])

    body = mock_call.call_args.kwargs["json"]
    assert body["shipmentIds"] == ["ship-1", "ship-2"]


# --------------- cancel_shipment ---------------

@patch("magazyn.allegro_api.shipment_management._call_with_refresh")
def test_cancel_shipment(mock_call):
    mock_call.return_value = _mock_response({
        "commandId": "cmd-cancel-1",
        "input": {"shipmentId": "ship-1"},
    })

    result = cancel_shipment("ship-1")

    assert result["input"]["shipmentId"] == "ship-1"
    body = mock_call.call_args.kwargs["json"]
    assert body["input"]["shipmentId"] == "ship-1"
    assert "commandId" in body


# --------------- get_cancel_command_status ---------------

@patch("magazyn.allegro_api.shipment_management._call_with_refresh")
def test_get_cancel_command_status(mock_call):
    mock_call.return_value = _mock_response({
        "commandId": "cmd-cancel-1",
        "status": "SUCCESS",
        "errors": [],
    })

    result = get_cancel_command_status("cmd-cancel-1")
    assert result["status"] == "SUCCESS"


# --------------- _call_with_refresh ---------------

@patch("magazyn.allegro_api.shipment_management._refresh_allegro_token")
@patch("magazyn.allegro_api.shipment_management._get_allegro_token")
@patch("magazyn.allegro_api.shipment_management._request_with_retry")
def test_call_with_refresh_401(mock_retry, mock_token, mock_refresh):
    from magazyn.allegro_api.shipment_management import _call_with_refresh

    mock_token.return_value = ("old-token", "refresh-token")
    mock_refresh.return_value = "new-token"

    ok_response = MagicMock()
    ok_response.json.return_value = {"ok": True}
    mock_retry.side_effect = [_mock_error_response(401), ok_response]

    result = _call_with_refresh(
        MagicMock(), "https://test.url", "test-endpoint",
    )

    assert result.json() == {"ok": True}
    mock_refresh.assert_called_once_with("refresh-token")
