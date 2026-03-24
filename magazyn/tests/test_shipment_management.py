"""Testy dla magazyn.allegro_api.shipment_management."""

import pytest
from unittest.mock import patch, MagicMock

from magazyn.allegro_api.shipment_management import (
    get_delivery_services,
    create_shipment,
    get_shipment_details,
    get_shipment_label,
    cancel_shipment,
    invalidate_delivery_services_cache,
    _CACHE_TTL,
)


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
    "city": "Warszawa",
    "zipCode": "00-001",
    "countryCode": "PL",
    "phone": "500000000",
    "email": "test@test.pl",
}

SAMPLE_RECEIVER = {
    "name": "Jan Kowalski",
    "street": "Odbiorcza 2",
    "city": "Krakow",
    "zipCode": "30-001",
    "countryCode": "PL",
    "phone": "600000000",
    "email": "jan@test.pl",
}

SAMPLE_PACKAGES = [
    {"weight": {"value": 1.0, "unit": "KILOGRAM"}}
]


# --------------- get_delivery_services ---------------

@patch("magazyn.allegro_api.shipment_management._call_with_refresh")
def test_get_delivery_services(mock_call):
    invalidate_delivery_services_cache()
    services = [{"id": "svc-1", "name": "InPost Paczkomaty"}]
    mock_call.return_value = _mock_response({"deliveryServices": services})

    result = get_delivery_services()

    assert result == services
    mock_call.assert_called_once()


@patch("magazyn.allegro_api.shipment_management._call_with_refresh")
def test_get_delivery_services_cached(mock_call):
    invalidate_delivery_services_cache()
    services = [{"id": "svc-1", "name": "DPD"}]
    mock_call.return_value = _mock_response({"deliveryServices": services})

    result1 = get_delivery_services()
    result2 = get_delivery_services()

    assert result1 == result2
    assert mock_call.call_count == 1  # drugie wywolanie z cache


@patch("magazyn.allegro_api.shipment_management._call_with_refresh")
def test_get_delivery_services_list_fallback(mock_call):
    """Gdy API zwraca liste zamiast obiektu z kluczem deliveryServices."""
    invalidate_delivery_services_cache()
    services = [{"id": "svc-1", "name": "DHL"}]
    mock_call.return_value = _mock_response(services)

    result = get_delivery_services()

    assert result == services


def test_invalidate_cache():
    invalidate_delivery_services_cache()
    # nie rzuca bledow


# --------------- create_shipment ---------------

@patch("magazyn.allegro_api.shipment_management._call_with_refresh")
def test_create_shipment(mock_call):
    mock_call.return_value = _mock_response({
        "id": "ship-123",
        "status": "DRAFT",
    })

    result = create_shipment(
        checkout_form_id="order-abc",
        delivery_service_id="svc-1",
        sender=SAMPLE_SENDER,
        receiver=SAMPLE_RECEIVER,
        packages=SAMPLE_PACKAGES,
    )

    assert result["id"] == "ship-123"
    body = mock_call.call_args.kwargs["json"]
    assert body["deliveryServiceId"] == "svc-1"
    assert body["checkoutForm"]["id"] == "order-abc"
    assert body["sender"] == SAMPLE_SENDER
    assert body["receiver"] == SAMPLE_RECEIVER
    assert body["packages"] == SAMPLE_PACKAGES
    assert "pickup" not in body


@patch("magazyn.allegro_api.shipment_management._call_with_refresh")
def test_create_shipment_with_pickup(mock_call):
    mock_call.return_value = _mock_response({"id": "ship-456", "status": "DRAFT"})
    pickup = {"date": "2026-03-15"}

    create_shipment(
        checkout_form_id="order-abc",
        delivery_service_id="svc-1",
        sender=SAMPLE_SENDER,
        receiver=SAMPLE_RECEIVER,
        packages=SAMPLE_PACKAGES,
        pickup=pickup,
    )

    body = mock_call.call_args.kwargs["json"]
    assert body["pickup"] == pickup


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

@patch("magazyn.allegro_api.shipment_management._refresh_allegro_token")
@patch("magazyn.allegro_api.shipment_management._get_allegro_token")
@patch("magazyn.allegro_api.shipment_management._request_with_retry")
def test_get_shipment_label_pdf(mock_retry, mock_token, mock_refresh):
    mock_token.return_value = ("test-token", "test-refresh")
    pdf_bytes = b"%PDF-1.4 test label data"
    response = MagicMock()
    response.content = pdf_bytes
    mock_retry.return_value = response

    result = get_shipment_label("ship-123")

    assert result == pdf_bytes
    headers = mock_retry.call_args.kwargs["headers"]
    assert headers["Accept"] == "application/pdf"


@patch("magazyn.allegro_api.shipment_management._refresh_allegro_token")
@patch("magazyn.allegro_api.shipment_management._get_allegro_token")
@patch("magazyn.allegro_api.shipment_management._request_with_retry")
def test_get_shipment_label_zpl(mock_retry, mock_token, mock_refresh):
    mock_token.return_value = ("test-token", "test-refresh")
    zpl_data = b"^XA^FO50,50^FDTEST^FS^XZ"
    response = MagicMock()
    response.content = zpl_data
    mock_retry.return_value = response

    result = get_shipment_label("ship-123", label_format="ZPL")

    assert result == zpl_data
    headers = mock_retry.call_args.kwargs["headers"]
    assert headers["Accept"] == "application/zpl"


@patch("magazyn.allegro_api.shipment_management._refresh_allegro_token")
@patch("magazyn.allegro_api.shipment_management._get_allegro_token")
@patch("magazyn.allegro_api.shipment_management._request_with_retry")
def test_get_shipment_label_404(mock_retry, mock_token, mock_refresh):
    mock_token.return_value = ("test-token", "test-refresh")
    exc = _mock_error_response(404)
    mock_retry.side_effect = exc

    with pytest.raises(RuntimeError, match="Etykieta nie dostepna"):
        get_shipment_label("ship-123")


@patch("magazyn.allegro_api.shipment_management._refresh_allegro_token")
@patch("magazyn.allegro_api.shipment_management._get_allegro_token")
@patch("magazyn.allegro_api.shipment_management._request_with_retry")
def test_get_shipment_label_token_refresh(mock_retry, mock_token, mock_refresh):
    mock_token.return_value = ("old-token", "refresh-token")
    mock_refresh.return_value = "new-token"

    # Pierwsze wywolanie: 401, drugie: sukces
    response_ok = MagicMock()
    response_ok.content = b"pdf-data"
    mock_retry.side_effect = [_mock_error_response(401), response_ok]

    result = get_shipment_label("ship-123")

    assert result == b"pdf-data"
    mock_refresh.assert_called_once_with("refresh-token")


# --------------- cancel_shipment ---------------

@patch("magazyn.allegro_api.shipment_management._call_with_refresh")
def test_cancel_shipment(mock_call):
    mock_call.return_value = _mock_response({"cancelled": ["ship-1", "ship-2"]})

    result = cancel_shipment(["ship-1", "ship-2"])

    assert result["cancelled"] == ["ship-1", "ship-2"]
    body = mock_call.call_args.kwargs["json"]
    assert body["shipmentIds"] == ["ship-1", "ship-2"]


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
