"""Testy modulu wfirma_api - klient, faktury, kontrahenci."""
from unittest.mock import patch, MagicMock
import pytest

from magazyn.wfirma_api.client import WFirmaClient, WFirmaError
from magazyn.wfirma_api.invoices import create_invoice, download_invoice_pdf, find_invoice
from magazyn.wfirma_api.contractors import (
    find_contractor,
    create_contractor,
    find_or_create_contractor,
)


# ===== Fixtures =====

@pytest.fixture
def client():
    """Klient wFirma z testowymi kluczami."""
    return WFirmaClient(
        access_key="test_access_key",
        secret_key="test_secret_key",
    )


@pytest.fixture
def client_with_app_key():
    """Klient z appKey."""
    return WFirmaClient(
        access_key="test_access",
        secret_key="test_secret",
        app_key="test_app",
        company_id="12345",
    )


# ===== WFirmaClient =====

def test_client_init_headers(client):
    """Sprawdz naglowki autoryzacji."""
    assert client._headers["accessKey"] == "test_access_key"
    assert client._headers["secretKey"] == "test_secret_key"
    assert "appKey" not in client._headers


def test_client_init_with_app_key(client_with_app_key):
    """Sprawdz appKey w naglowkach."""
    assert client_with_app_key._headers["appKey"] == "test_app"
    assert client_with_app_key.company_id == "12345"


def test_client_missing_keys():
    """Blad bez wymaganych kluczy."""
    with pytest.raises(ValueError, match="wymagane"):
        WFirmaClient(access_key="", secret_key="s")
    with pytest.raises(ValueError, match="wymagane"):
        WFirmaClient(access_key="a", secret_key="")


@patch("magazyn.wfirma_api.client.requests.post")
def test_client_request_success(mock_post, client):
    """Poprawny request."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "status": {"code": "OK"},
        "invoices": [{"invoice": {"id": 1}}],
    }
    mock_post.return_value = mock_resp

    result = client.request("invoices/add", data={"test": True})
    assert result["invoices"][0]["invoice"]["id"] == 1


@patch("magazyn.wfirma_api.client.requests.post")
def test_client_request_api_error(mock_post, client):
    """Blad API zwrocony przez wFirma."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "status": {"code": "ERROR", "message": "Nieprawidlowy NIP"},
    }
    mock_post.return_value = mock_resp

    with pytest.raises(WFirmaError, match="Nieprawidlowy NIP"):
        client.request("invoices/add")


@patch("magazyn.wfirma_api.client.requests.get")
def test_client_download(mock_get, client):
    """Pobieranie pliku binarnego."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b"%PDF-1.4 test content"
    mock_resp.raise_for_status.return_value = None
    mock_get.return_value = mock_resp

    data = client.download("invoices/download/42")
    assert data == b"%PDF-1.4 test content"


def test_client_from_settings():
    """Tworzenie klienta z settings_store."""
    mock_settings = {
        "WFIRMA_ACCESS_KEY": "key1",
        "WFIRMA_SECRET_KEY": "key2",
        "WFIRMA_APP_KEY": "key3",
        "WFIRMA_COMPANY_ID": "999",
    }
    mock_store = MagicMock()
    mock_store.get = lambda k: mock_settings.get(k)
    with patch("magazyn.settings_store.settings_store", mock_store):
        c = WFirmaClient.from_settings()
        assert c._headers["accessKey"] == "key1"
        assert c._headers["secretKey"] == "key2"
        assert c._headers["appKey"] == "key3"
        assert c.company_id == "999"


def test_client_from_settings_missing():
    """Blad gdy brak kluczy w settings."""
    mock_store = MagicMock()
    mock_store.get = lambda k: None
    with patch("magazyn.settings_store.settings_store", mock_store):
        with pytest.raises(WFirmaError, match="Brak kluczy"):
            WFirmaClient.from_settings()


# ===== Invoices =====

def test_create_invoice_with_contractor_id(client):
    """Tworzenie faktury z ID kontrahenta."""
    client.request = MagicMock(return_value={
        "invoices": [{
            "invoice": {
                "id": 42,
                "fullnumber": "FV 1/06/2025",
                "total": 110.70,
            }
        }]
    })

    result = create_invoice(
        client,
        contractor_id=10,
        items=[
            {"name": "Szelki M", "price": 89.99, "vat": "23"},
            {"name": "Smycz 2m", "price": 20.71, "count": 1, "vat": "23"},
        ],
    )

    assert result["invoice_id"] == 42
    assert result["invoice_number"] == "FV 1/06/2025"
    assert result["total"] == 110.70

    call_data = client.request.call_args[1]["data"]
    invoice = call_data["invoices"][0]["invoice"]
    assert invoice["contractor"]["id"] == 10
    assert len(invoice["invoicecontents"]) == 2
    assert invoice["type"] == "bill"
    assert invoice["price_type"] == "brutto"


def test_create_invoice_with_contractor_data(client):
    """Tworzenie faktury z danymi inline kontrahenta."""
    client.request = MagicMock(return_value={
        "invoices": [{
            "invoice": {
                "id": 43,
                "fullnumber": "FV 2/06/2025",
                "total": 50.00,
            }
        }]
    })

    result = create_invoice(
        client,
        contractor_data={
            "name": "Jan Kowalski",
            "street": "Testowa 1",
            "zip": "00-001",
            "city": "Warszawa",
            "nip": "1234567890",
        },
        items=[{"name": "Obroza S", "price": 50.00}],
    )

    assert result["invoice_id"] == 43
    call_data = client.request.call_args[1]["data"]
    contractor = call_data["invoices"][0]["invoice"]["contractor"]
    assert contractor["name"] == "Jan Kowalski"
    assert contractor["nip"] == "1234567890"


def test_create_invoice_empty_response(client):
    """Blad gdy wFirma zwroci pusta odpowiedz."""
    client.request = MagicMock(return_value={"invoices": []})

    with pytest.raises(WFirmaError, match="nie zwrocil danych faktury"):
        create_invoice(
            client,
            contractor_id=1,
            items=[{"name": "test", "price": 10.0}],
        )


def test_download_invoice_pdf(client):
    """Pobieranie PDF faktury."""
    pdf_content = b"%PDF-1.4 " + b"x" * 200
    client.download = MagicMock(return_value=pdf_content)

    result = download_invoice_pdf(client, 42)
    assert result == pdf_content
    client.download.assert_called_once_with("invoices/download/42")


def test_download_invoice_pdf_too_small(client):
    """Blad gdy PDF za maly."""
    client.download = MagicMock(return_value=b"x" * 50)

    with pytest.raises(WFirmaError, match="zbyt maly"):
        download_invoice_pdf(client, 42)


def test_find_invoice_found(client):
    """Wyszukiwanie istniejącej faktury."""
    client.request = MagicMock(return_value={
        "invoices": {
            "0": {
                "invoice": {
                    "id": 42,
                    "fullnumber": "FV 1/06/2025",
                    "total": 110.70,
                }
            },
            "parameters": {
                "total": 1,
            },
        }
    })

    result = find_invoice(client, "FV 1/06/2025")
    assert result["id"] == 42
    assert result["fullnumber"] == "FV 1/06/2025"


def test_find_invoice_not_found(client):
    """Wyszukiwanie nieistniejacej faktury."""
    client.request = MagicMock(return_value={"invoices": []})

    result = find_invoice(client, "FV 999/06/2025")
    assert result is None


# ===== Contractors =====

def test_find_contractor_by_nip(client):
    """Wyszukiwanie kontrahenta po NIP."""
    client.request = MagicMock(return_value={
        "contractors": [{
            "contractor": {
                "id": 5,
                "name": "Firma XYZ",
                "nip": "1234567890",
            }
        }]
    })

    result = find_contractor(client, nip="1234567890")
    assert result["id"] == 5
    assert result["name"] == "Firma XYZ"

    call_data = client.request.call_args[1]["data"]
    condition = call_data["contractors"]["parameters"]["conditions"]["condition"]
    assert condition["field"] == "nip"
    assert condition["value"] == "1234567890"


def test_find_contractor_by_name(client):
    """Wyszukiwanie kontrahenta po nazwie (fallback)."""
    client.request = MagicMock(return_value={
        "contractors": [{
            "contractor": {"id": 6, "name": "Jan Kowalski"}
        }]
    })

    result = find_contractor(client, name="Jan Kowalski")
    assert result["id"] == 6

    call_data = client.request.call_args[1]["data"]
    condition = call_data["contractors"]["parameters"]["conditions"]["condition"]
    assert condition["field"] == "name"


def test_find_contractor_rejects_mismatched_nip(client):
    """Nie uzywaj kontrahenta, jesli odpowiedz ma inny NIP niz zapytanie."""
    client.request = MagicMock(return_value={
        "contractors": [{
            "contractor": {
                "id": 138282910,
                "name": "Jinjiang",
                "nip": "4201000090",
            }
        }]
    })

    result = find_contractor(client, nip="5270100493")
    assert result is None


def test_find_contractor_not_found(client):
    """Kontrahent nie istnieje."""
    client.request = MagicMock(return_value={"contractors": []})

    result = find_contractor(client, nip="0000000000")
    assert result is None


def test_find_contractor_no_params(client):
    """Brak NIP i nazwy - zwraca None."""
    result = find_contractor(client)
    assert result is None


def test_create_contractor(client):
    """Tworzenie nowego kontrahenta."""
    client.request = MagicMock(return_value={
        "contractors": [{
            "contractor": {"id": 99, "name": "Nowa Firma"}
        }]
    })

    result = create_contractor(
        client,
        name="Nowa Firma",
        street="Nowa 5",
        zip_code="30-001",
        city="Krakow",
        nip="9876543210",
    )

    assert result["contractor_id"] == 99
    assert result["name"] == "Nowa Firma"

    call_data = client.request.call_args[1]["data"]
    contractor = call_data["contractors"][0]["contractor"]
    assert contractor["nip"] == "9876543210"
    assert contractor["zip"] == "30-001"


def test_create_contractor_empty_response(client):
    """Blad gdy wFirma nie zwroci danych."""
    client.request = MagicMock(return_value={"contractors": []})

    with pytest.raises(WFirmaError, match="nie zwrocil danych kontrahenta"):
        create_contractor(client, name="Test")


def test_find_or_create_contractor_existing(client):
    """find_or_create - kontrahent istnieje."""
    client.request = MagicMock(return_value={
        "contractors": [{
            "contractor": {"id": 5, "name": "Firma XYZ", "nip": "111"}
        }]
    })

    result = find_or_create_contractor(client, name="Firma XYZ", nip="111")
    assert result == 5
    # Tylko find, bez add
    assert client.request.call_count == 1
    assert client.request.call_args[0][0] == "contractors/find"


def test_find_or_create_contractor_new(client):
    """find_or_create - kontrahent nie istnieje, tworzy nowego."""
    # Pierwsze wywolanie (find) - brak wynikow
    # Drugie wywolanie (add) - zwraca nowego
    client.request = MagicMock(side_effect=[
        {"contractors": []},  # find - nie znaleziono
        {"contractors": [{"contractor": {"id": 77, "name": "New"}}]},  # add
    ])

    result = find_or_create_contractor(client, name="New", nip="222")
    assert result == 77
    assert client.request.call_count == 2


def test_find_or_create_contractor_new_on_mismatched_nip(client):
    """Gdy find zwroci zly NIP, tworzymy nowego kontrahenta."""
    client.request = MagicMock(side_effect=[
        {"contractors": [{"contractor": {"id": 1, "name": "Inny", "nip": "000"}}]},
        {"contractors": [{"contractor": {"id": 77, "name": "Nowy", "nip": "222"}}]},
    ])

    result = find_or_create_contractor(client, name="Nowy", nip="222")
    assert result == 77
    assert client.request.call_count == 2
