"""Testy dla magazyn.allegro_api.fulfillment."""

import pytest
from unittest.mock import patch, MagicMock

from magazyn.allegro_api.fulfillment import (
    update_fulfillment_status,
    add_shipment_tracking,
    get_shipment_tracking_numbers,
    VALID_FULFILLMENT_STATUSES,
    _call_with_refresh,
)


# --------------- helpers ---------------

def _mock_token():
    return ("test-token", "test-refresh")


def _mock_response(json_data, status_code=200):
    resp = MagicMock()
    resp.json.return_value = json_data
    resp.status_code = status_code
    return resp


def _mock_error_response(status_code):
    resp = MagicMock()
    resp.status_code = status_code
    exc = Exception("HTTP error")
    exc.response = resp
    return exc


# --------------- update_fulfillment_status ---------------

@patch("magazyn.allegro_api.fulfillment._call_with_refresh")
def test_update_fulfillment_status_success(mock_call):
    mock_call.return_value = _mock_response({"status": "PROCESSING"})

    result = update_fulfillment_status("abc-123", "PROCESSING")

    assert result == {"status": "PROCESSING"}
    call_args = mock_call.call_args
    assert call_args.kwargs["json"] == {"status": "PROCESSING"}
    assert "abc-123" in call_args.args[1]


@patch("magazyn.allegro_api.fulfillment._call_with_refresh")
def test_update_fulfillment_with_shipment_summary(mock_call):
    mock_call.return_value = _mock_response({"status": "SENT"})
    summary = {"lineItemsSent": "ALL"}

    result = update_fulfillment_status(
        "abc-123", "SENT", shipment_summary=summary
    )

    assert result == {"status": "SENT"}
    body = mock_call.call_args.kwargs["json"]
    assert body["status"] == "SENT"
    assert body["shipmentSummary"] == {"lineItemsSent": "ALL"}


def test_update_fulfillment_invalid_status():
    with pytest.raises(ValueError, match="Nieprawidlowy status"):
        update_fulfillment_status("abc-123", "INVALID_STATUS")


@patch("magazyn.allegro_api.fulfillment._call_with_refresh")
def test_update_fulfillment_all_valid_statuses(mock_call):
    """Kazdy prawidlowy status powinien przejsc walidacje."""
    mock_call.return_value = _mock_response({"status": "OK"})

    for status in VALID_FULFILLMENT_STATUSES:
        update_fulfillment_status("abc-123", status)

    assert mock_call.call_count == len(VALID_FULFILLMENT_STATUSES)


# --------------- add_shipment_tracking ---------------

@patch("magazyn.allegro_api.fulfillment._call_with_refresh")
def test_add_shipment_tracking_success(mock_call):
    mock_call.return_value = _mock_response({
        "id": "ship-1",
        "carrierId": "INPOST",
        "waybill": "123456789",
    })

    result = add_shipment_tracking(
        "abc-123", carrier_id="INPOST", waybill="123456789"
    )

    assert result["carrierId"] == "INPOST"
    assert result["waybill"] == "123456789"

    body = mock_call.call_args.kwargs["json"]
    assert body["carrierId"] == "INPOST"
    assert body["waybill"] == "123456789"
    assert body["lineItemsSent"] == "ALL"


@patch("magazyn.allegro_api.fulfillment._call_with_refresh")
def test_add_shipment_tracking_partial(mock_call):
    mock_call.return_value = _mock_response({"id": "ship-2"})

    add_shipment_tracking(
        "abc-123",
        carrier_id="DHL",
        waybill="999",
        line_items_sent="SOME",
    )

    body = mock_call.call_args.kwargs["json"]
    assert body["lineItemsSent"] == "SOME"


# --------------- get_shipment_tracking_numbers ---------------

@patch("magazyn.allegro_api.fulfillment._call_with_refresh")
def test_get_shipment_tracking_numbers(mock_call):
    mock_call.return_value = _mock_response({
        "shipments": [
            {"carrierId": "INPOST", "waybill": "111"},
            {"carrierId": "DHL", "waybill": "222"},
        ]
    })

    result = get_shipment_tracking_numbers("abc-123")

    assert len(result) == 2
    assert result[0]["waybill"] == "111"
    assert result[1]["carrierId"] == "DHL"


@patch("magazyn.allegro_api.fulfillment._call_with_refresh")
def test_get_shipment_tracking_empty(mock_call):
    mock_call.return_value = _mock_response({"shipments": []})

    result = get_shipment_tracking_numbers("abc-123")

    assert result == []


# --------------- _call_with_refresh (token refresh) ---------------

@patch("magazyn.allegro_api.fulfillment._refresh_allegro_token")
@patch("magazyn.allegro_api.fulfillment._get_allegro_token")
@patch("magazyn.allegro_api.fulfillment._request_with_retry")
def test_call_with_refresh_token_refresh_on_401(
    mock_retry, mock_get_token, mock_refresh
):
    mock_get_token.return_value = ("old-token", "refresh-token")
    mock_refresh.return_value = "new-token"

    # Pierwsze wywolanie 401, drugie OK
    error_resp = MagicMock()
    error_resp.status_code = 401
    exc = Exception("Unauthorized")
    exc.response = error_resp

    ok_resp = _mock_response({"status": "OK"})
    mock_retry.side_effect = [exc, ok_resp]

    result = _call_with_refresh(
        MagicMock(), "http://test", "test-endpoint"
    )

    assert result == ok_resp
    mock_refresh.assert_called_once_with("refresh-token")


@patch("magazyn.allegro_api.fulfillment._get_allegro_token")
@patch("magazyn.allegro_api.fulfillment._request_with_retry")
def test_call_with_refresh_no_double_refresh(mock_retry, mock_get_token):
    """Nie odswiezaj tokenu dwa razy."""
    mock_get_token.return_value = ("token", "refresh")

    error_resp = MagicMock()
    error_resp.status_code = 401
    exc = Exception("Unauthorized")
    exc.response = error_resp

    mock_retry.side_effect = exc

    with patch("magazyn.allegro_api.fulfillment._refresh_allegro_token") as mock_ref:
        mock_ref.return_value = "new-token"
        # Po odswiezeniu tokenu, drugi 401 powinien rzucic wyjatek
        with pytest.raises(Exception, match="Unauthorized"):
            _call_with_refresh(MagicMock(), "http://test", "ep")
