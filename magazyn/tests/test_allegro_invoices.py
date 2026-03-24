"""Testy modulu allegro_api/invoices.py - upload faktur do zamowien Allegro."""
from unittest.mock import patch, MagicMock

import pytest
from requests.exceptions import HTTPError

from magazyn.allegro_api.invoices import upload_invoice_to_allegro


def _mock_response(data=None, status_code=200):
    """Tworzy mock odpowiedzi HTTP."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = data or {}
    resp.headers = {}
    resp.raise_for_status.return_value = None
    return resp


def _mock_error_response(status_code=401):
    """Tworzy mock blednej odpowiedzi HTTP."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = {}
    resp.json.return_value = {"errors": [{"code": "UNAUTHORIZED"}]}
    error = HTTPError(response=resp)
    resp.raise_for_status.side_effect = error
    return resp


@patch("magazyn.allegro_api.invoices._get_allegro_token", return_value=("token123", "refresh123"))
@patch("magazyn.allegro_api.invoices._request_with_retry")
def test_upload_invoice_success(mock_request, mock_token):
    """Pelny flow: create metadata + upload PDF."""
    # Krok 1: POST - metadata
    create_resp = _mock_response({"id": "inv-uuid-001"})
    # Krok 2: PUT - upload
    upload_resp = _mock_response()
    mock_request.side_effect = [create_resp, upload_resp]

    result = upload_invoice_to_allegro(
        checkout_form_id="cf-uuid-123",
        invoice_number="FV/2025/06/001",
        pdf_data=b"%PDF-1.4 test data",
    )

    assert result["invoice_id"] == "inv-uuid-001"
    assert result["invoice_number"] == "FV/2025/06/001"
    assert mock_request.call_count == 2

    # Sprawdz krok 1 - POST metadata
    call1 = mock_request.call_args_list[0]
    assert "order/checkout-forms/cf-uuid-123/invoices" in call1[0][1]
    assert call1[1]["json"]["invoiceNumber"] == "FV/2025/06/001"

    # Sprawdz krok 2 - PUT upload
    call2 = mock_request.call_args_list[1]
    assert "inv-uuid-001/file" in call2[0][1]
    assert call2[1]["data"] == b"%PDF-1.4 test data"


@patch("magazyn.allegro_api.invoices._get_allegro_token", return_value=("token123", "refresh123"))
@patch("magazyn.allegro_api.invoices._request_with_retry")
def test_upload_invoice_custom_filename(mock_request, mock_token):
    """Upload z wlasna nazwa pliku."""
    mock_request.side_effect = [
        _mock_response({"id": "inv-002"}),
        _mock_response(),
    ]

    result = upload_invoice_to_allegro(
        checkout_form_id="cf-uuid-456",
        invoice_number="FV/2025/06/002",
        pdf_data=b"%PDF content",
        file_name="mojafaktura.pdf",
    )

    call1 = mock_request.call_args_list[0]
    assert call1[1]["json"]["file"]["name"] == "mojafaktura.pdf"


@patch("magazyn.allegro_api.invoices._get_allegro_token", return_value=("token123", "refresh123"))
@patch("magazyn.allegro_api.invoices._refresh_allegro_token", return_value="new_token")
@patch("magazyn.allegro_api.invoices._request_with_retry")
def test_upload_invoice_token_refresh(mock_request, mock_refresh, mock_token):
    """Odswiezenie tokenu przy 401 na create metadata."""
    error_resp = _mock_error_response(401)
    mock_request.side_effect = [
        HTTPError(response=error_resp),  # 1st call fails
        _mock_response({"id": "inv-003"}),  # retry succeeds
        _mock_response(),  # upload succeeds
    ]

    result = upload_invoice_to_allegro(
        checkout_form_id="cf-uuid-789",
        invoice_number="FV/2025/06/003",
        pdf_data=b"%PDF test",
    )

    assert result["invoice_id"] == "inv-003"
    mock_refresh.assert_called_once_with("refresh123")


def test_upload_invoice_empty_pdf():
    """Blad przy pustym PDF."""
    with pytest.raises(ValueError, match="Pusty"):
        upload_invoice_to_allegro(
            checkout_form_id="cf-uuid-123",
            invoice_number="FV/2025/06/001",
            pdf_data=b"",
        )


@patch("magazyn.allegro_api.invoices._get_allegro_token", return_value=("token123", "refresh123"))
@patch("magazyn.allegro_api.invoices._request_with_retry")
def test_upload_invoice_no_id_in_response(mock_request, mock_token):
    """Blad gdy Allegro nie zwroci invoice ID."""
    mock_request.return_value = _mock_response({})

    with pytest.raises(RuntimeError, match="nie zwrocilo invoice_id"):
        upload_invoice_to_allegro(
            checkout_form_id="cf-uuid-123",
            invoice_number="FV/01",
            pdf_data=b"%PDF data",
        )


@patch("magazyn.allegro_api.invoices._get_allegro_token", return_value=("token123", "refresh123"))
@patch("magazyn.allegro_api.invoices._request_with_retry")
def test_upload_invoice_generates_filename(mock_request, mock_token):
    """Automatyczne generowanie nazwy pliku z numeru faktury."""
    mock_request.side_effect = [
        _mock_response({"id": "inv-004"}),
        _mock_response(),
    ]

    upload_invoice_to_allegro(
        checkout_form_id="cf-uuid-999",
        invoice_number="FV/2025/06/004",
        pdf_data=b"%PDF data",
    )

    call1 = mock_request.call_args_list[0]
    file_name = call1[1]["json"]["file"]["name"]
    assert file_name == "FV_2025_06_004.pdf"
    assert "/" not in file_name
