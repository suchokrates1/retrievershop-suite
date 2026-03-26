"""
Tworzenie faktur VAT w wFirma i pobieranie PDF.

Endpointy:
- POST /invoices/add - tworzenie faktury (w tym korekt)
- GET /invoices/download/{id} - pobieranie PDF
- GET /invoices/find - wyszukiwanie faktur
- GET /invoices/get/{id} - pobranie pelnych danych faktury
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
    invoice_type: str = "bill",
    description: Optional[str] = None,
) -> dict:
    """
    Utworz fakture/rachunek w wFirma.

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
    invoice_type : str
        Typ dokumentu: "bill" (rachunek, nie-VAT), "normal" (faktura VAT),
        "proforma". Domyslnie "bill".
    description : str, optional
        Opis na fakturze (np. numer zamowienia).

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

    invoice = {
        "paymentmethod": payment_method,
        "paymentdate": payment_date,
        "date": invoice_date,
        "type": invoice_type,
        "price_type": "brutto",
        "contractor": contractor,
        "invoicecontents": invoice_contents,
    }
    if description:
        invoice["description"] = description

    invoice_data = {
        "invoices": [{
            "invoice": invoice,
        }]
    }

    if series_id:
        invoice_data["invoices"][0]["invoice"]["series"] = {"id": series_id}

    result = client.request("invoices/add", data=invoice_data)

    # Wyciagnij dane faktury z odpowiedzi
    invoices = result.get("invoices", [])
    if not invoices:
        raise WFirmaError("wFirma nie zwrocil danych faktury", details=result)

    # wFirma zwraca dict z numerycznym kluczem lub liste
    if isinstance(invoices, list):
        invoice = invoices[0].get("invoice", {})
    else:
        first_key = next((k for k in sorted(invoices) if k != "parameters"), None)
        invoice = invoices[first_key].get("invoice", {}) if first_key else {}
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
        "invoices": {
            "parameters": {
                "conditions": {
                    "condition": {
                        "field": "fullnumber",
                        "operator": "eq",
                        "value": invoice_number,
                    }
                }
            }
        }
    }

    result = client.request("invoices/find", data=data)
    invoices = result.get("invoices", {})

    if not invoices or not any(k != "parameters" for k in invoices):
        return None

    # Pierwszy wynik (klucz "0")
    first_key = next(k for k in sorted(invoices) if k != "parameters")
    return invoices[first_key].get("invoice")


def get_invoice(client: WFirmaClient, invoice_id: int) -> dict:
    """
    Pobierz pelne dane faktury (z pozycjami).

    Parameters
    ----------
    client : WFirmaClient
        Klient API.
    invoice_id : int
        ID faktury w wFirma.

    Returns
    -------
    dict
        Dane faktury wraz z invoicecontents.
    """
    result = client.request(f"invoices/get/{invoice_id}")
    invoices = result.get("invoices", {})

    first_key = next((k for k in sorted(invoices) if k != "parameters"), None)
    if first_key is None:
        raise WFirmaError(f"Nie znaleziono faktury id={invoice_id}")

    return invoices[first_key].get("invoice", {})


def create_correction_invoice(
    client: WFirmaClient,
    *,
    original_invoice_id: int,
    corrected_items: Optional[list[dict]] = None,
    description: str = "",
    payment_method: str = "transfer",
) -> dict:
    """
    Wystaw korekte do faktury/rachunku w wFirma.

    Jesli corrected_items jest None, tworzy korekte zerujaca
    (wszystkie pozycje na count=0).

    Jesli corrected_items jest podane, koryguje TYLKO wymienione pozycje.

    Parameters
    ----------
    client : WFirmaClient
        Klient API.
    original_invoice_id : int
        ID oryginalnej faktury do skorygowania.
    corrected_items : list[dict], optional
        Lista skorygowanych pozycji. Kazdy element:
        {"original_content_id": int, "count": int/float}
        count = nowa ilosc po korekcie (0 = pelny zwrot pozycji).
        Jesli None - korekta zerujaca (count=0 dla WSZYSTKICH pozycji).
    description : str
        Opis korekty (np. "Zwrot pelny zamowienia #12345").
    payment_method : str
        Metoda platnosci. Domyslnie "transfer".

    Returns
    -------
    dict
        {"invoice_id": int, "invoice_number": str, "total": float}
    """
    original = get_invoice(client, original_invoice_id)
    original_type = original.get("type", "bill")

    # Typ korekty odpowiada typowi oryginalu
    correction_type = original_type if original_type in ("bill", "normal") else "bill"

    # Buduj pozycje korekty
    contents_data = original.get("invoicecontents", {})
    original_contents = []
    for k in sorted(contents_data):
        if k == "parameters":
            continue
        content = contents_data[k].get("invoicecontent", {})
        if content:
            original_contents.append(content)

    if not original_contents:
        raise WFirmaError(
            f"Faktura id={original_invoice_id} nie ma pozycji do korekty"
        )

    # Mapowanie zmian: original_content_id -> nowy count
    count_map = {}
    if corrected_items is not None:
        for item in corrected_items:
            count_map[int(item["original_content_id"])] = item["count"]

    invoice_contents = []
    for content in original_contents:
        content_id = int(content["id"])

        if corrected_items is not None:
            # Selektywna korekta - uwzgledniaj TYLKO pozycje z corrected_items
            if content_id not in count_map:
                continue
            new_count = count_map[content_id]
        else:
            # Korekta zerujaca - wszystkie pozycje na 0
            new_count = 0

        ic = {
            "name": content["name"],
            "count": new_count,
            "price": content["price"],
            "unit": content.get("unit", "szt."),
            "vat_code": content.get("vat_code", {"id": 233}),
            "parent": {"id": content_id},
        }

        invoice_contents.append({"invoicecontent": ic})

    if not invoice_contents:
        raise WFirmaError("Brak pozycji do korekty po filtrowaniu")

    invoice_data = {
        "invoices": [{
            "invoice": {
                "type": "correction",
                "correction_type": correction_type,
                "paymentmethod": payment_method,
                "description": description,
                "schema": "normal",
                "parent": {"id": original_invoice_id},
                "invoicecontents": invoice_contents,
            }
        }]
    }

    result = client.request("invoices/add", data=invoice_data)
    invoices = result.get("invoices", {})
    if not invoices:
        raise WFirmaError("wFirma nie zwrocil danych korekty", details=result)

    # Odpowiedz moze miec klucz "0" lub byc lista
    if isinstance(invoices, list):
        inv = invoices[0].get("invoice", {})
    else:
        first_key = next((k for k in sorted(invoices) if k != "parameters"), None)
        inv = invoices[first_key].get("invoice", {}) if first_key else {}

    invoice_id = inv.get("id")
    invoice_number = inv.get("fullnumber", "")
    total = inv.get("total", 0.0)

    logger.info(
        "Utworzono korekte wFirma: %s (id=%s, total=%.2f, do faktury id=%s)",
        invoice_number, invoice_id, float(total), original_invoice_id,
    )

    return {
        "invoice_id": invoice_id,
        "invoice_number": invoice_number,
        "total": float(total),
    }
