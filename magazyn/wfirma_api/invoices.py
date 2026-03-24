"""
Tworzenie faktur VAT w wFirma i pobieranie PDF.

Endpointy:
- POST /invoices/add - tworzenie faktury
- GET /invoices/download/{id} - pobieranie PDF
- GET /invoices/find - wyszukiwanie faktur
"""
import logging
from datetime import date
from typing import Optional

from .client import WFirmaClient, WFirmaError

logger = logging.getLogger(__name__)


def create_invoice(
    client: WFirmaClient,
    *,
    contractor_id: Optional[int] = None,
    contractor_data: Optional[dict] = None,
    items: list[dict],
    payment_method: str = "transfer",
    payment_date: Optional[str] = None,
    invoice_date: Optional[str] = None,
    series_id: Optional[int] = None,
) -> dict:
    """
    Utworz fakture VAT w wFirma.

    Parameters
    ----------
    client : WFirmaClient
        Klient API.
    contractor_id : int, optional
        ID istniejacego kontrahenta w wFirma.
    contractor_data : dict, optional
        Dane kontrahenta inline (jesli nie ma contractor_id).
        Klucze: name, street, zip, city, nip (opcj.), country (domysl. "PL").
    items : list[dict]
        Pozycje faktury. Kazdy element:
        {"name": str, "unit": str, "count": int/float,
         "price": float (brutto), "vat": str (np. "23", "8", "zw")}
    payment_method : str
        "transfer", "cash", "card". Domyslnie "transfer".
    payment_date : str, optional
        Data platnosci (YYYY-MM-DD). Domyslnie dzisiejsza.
    invoice_date : str, optional
        Data wystawienia (YYYY-MM-DD). Domyslnie dzisiejsza.
    series_id : int, optional
        ID serii numeracji faktur.

    Returns
    -------
    dict
        {"invoice_id": int, "invoice_number": str, "total": float}
    """
    today = date.today().isoformat()
    if not payment_date:
        payment_date = today
    if not invoice_date:
        invoice_date = today

    # Buduj dane kontrahenta
    contractor = {}
    if contractor_id:
        contractor["id"] = contractor_id
    elif contractor_data:
        contractor = {
            "name": contractor_data.get("name", ""),
            "street": contractor_data.get("street", ""),
            "zip": contractor_data.get("zip", ""),
            "city": contractor_data.get("city", ""),
            "country": contractor_data.get("country", "PL"),
        }
        nip = contractor_data.get("nip")
        if nip:
            contractor["nip"] = nip

    # Buduj pozycje faktury
    invoice_contents = []
    for item in items:
        invoice_contents.append({
            "invoicecontent": {
                "name": item["name"],
                "unit": item.get("unit", "szt."),
                "count": item.get("count", 1),
                "price": item["price"],
                "vat": str(item.get("vat", "23")),
            }
        })

    invoice_data = {
        "invoices": [{
            "invoice": {
                "paymentmethod": payment_method,
                "paymentdate": payment_date,
                "date": invoice_date,
                "type": "normal",
                "price_type": "brutto",
                "contractor": contractor,
                "invoicecontents": invoice_contents,
            }
        }]
    }

    if series_id:
        invoice_data["invoices"][0]["invoice"]["series"] = {"id": series_id}

    result = client.request("invoices/add", data=invoice_data)

    # Wyciagnij dane faktury z odpowiedzi
    invoices = result.get("invoices", [])
    if not invoices:
        raise WFirmaError("wFirma nie zwrocil danych faktury", details=result)

    invoice = invoices[0].get("invoice", {})
    invoice_id = invoice.get("id")
    invoice_number = invoice.get("fullnumber", "")
    total = invoice.get("total", 0.0)

    logger.info(
        "Utworzono fakture wFirma: %s (id=%s, total=%.2f)",
        invoice_number, invoice_id, float(total),
    )

    return {
        "invoice_id": invoice_id,
        "invoice_number": invoice_number,
        "total": float(total),
    }


def download_invoice_pdf(client: WFirmaClient, invoice_id: int) -> bytes:
    """
    Pobierz PDF faktury z wFirma.

    Parameters
    ----------
    client : WFirmaClient
        Klient API.
    invoice_id : int
        ID faktury w wFirma.

    Returns
    -------
    bytes
        Zawartosc pliku PDF.
    """
    pdf_data = client.download(f"invoices/download/{invoice_id}")

    if not pdf_data or len(pdf_data) < 100:
        raise WFirmaError(
            f"Pobrano pusty lub zbyt maly PDF faktury (id={invoice_id})"
        )

    logger.info("Pobrano PDF faktury wFirma id=%s (%d bajtow)", invoice_id, len(pdf_data))
    return pdf_data


def find_invoice(client: WFirmaClient, invoice_number: str) -> Optional[dict]:
    """
    Wyszukaj fakture po numerze.

    Parameters
    ----------
    client : WFirmaClient
        Klient API.
    invoice_number : str
        Numer faktury (np. "FV 12/03/2026").

    Returns
    -------
    dict or None
        Dane faktury lub None jesli nie znaleziono.
    """
    data = {
        "invoices": [{
            "parameters": {
                "conditions": {
                    "condition": {
                        "field": "fullnumber",
                        "operator": "eq",
                        "value": invoice_number,
                    }
                }
            }
        }]
    }

    result = client.request("invoices/find", data=data)
    invoices = result.get("invoices", [])

    if not invoices:
        return None

    return invoices[0].get("invoice")
