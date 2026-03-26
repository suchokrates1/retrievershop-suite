"""
Zarzadzanie kontrahentami w wFirma.

Endpointy:
- POST /contractors/add - tworzenie kontrahenta
- POST /contractors/find - wyszukiwanie kontrahentow
"""
import logging
from typing import Optional

from .client import WFirmaClient, WFirmaError

logger = logging.getLogger(__name__)


def find_contractor(
    client: WFirmaClient,
    *,
    nip: Optional[str] = None,
    name: Optional[str] = None,
) -> Optional[dict]:
    """
    Wyszukaj kontrahenta w wFirma po NIP lub nazwie.

    Parameters
    ----------
    client : WFirmaClient
        Klient API.
    nip : str, optional
        NIP kontrahenta (priorytetowe wyszukiwanie).
    name : str, optional
        Nazwa kontrahenta (fallback).

    Returns
    -------
    dict or None
        Dane kontrahenta (id, name, nip, ...) lub None.
    """
    if not nip and not name:
        return None

    # Priorytet: szukaj po NIP
    field = "nip" if nip else "name"
    value = nip if nip else name

    data = {
        "contractors": [{
            "parameters": {
                "conditions": {
                    "condition": {
                        "field": field,
                        "operator": "eq",
                        "value": value,
                    }
                }
            }
        }]
    }

    result = client.request("contractors/find", data=data)
    logger.debug("find_contractor odpowiedz wFirma: %s", result)
    contractors = result.get("contractors", [])

    if not contractors:
        return None

    # wFirma zwraca dict z numerycznym kluczem lub liste
    if isinstance(contractors, list):
        contractor = contractors[0].get("contractor", {})
    else:
        first_key = next((k for k in sorted(contractors) if k != "parameters"), None)
        contractor = contractors[first_key].get("contractor", {}) if first_key else {}
    logger.debug("Znaleziono kontrahenta wFirma: %s (id=%s)", contractor.get("name"), contractor.get("id"))
    return contractor


def create_contractor(
    client: WFirmaClient,
    *,
    name: str,
    street: str = "",
    zip_code: str = "",
    city: str = "",
    country: str = "PL",
    nip: Optional[str] = None,
    email: Optional[str] = None,
    phone: Optional[str] = None,
) -> dict:
    """
    Utworz kontrahenta w wFirma.

    Parameters
    ----------
    client : WFirmaClient
        Klient API.
    name : str
        Nazwa kontrahenta (firma lub imie i nazwisko).
    street, zip_code, city, country : str
        Adres.
    nip : str, optional
        NIP (dla firm).
    email, phone : str, optional
        Dane kontaktowe.

    Returns
    -------
    dict
        {"contractor_id": int, "name": str}
    """
    contractor = {
        "name": name,
        "street": street,
        "zip": zip_code,
        "city": city,
        "country": country,
    }
    if nip:
        contractor["nip"] = nip
    if email:
        contractor["email"] = email
    if phone:
        contractor["phone"] = phone

    data = {
        "contractors": [{
            "contractor": contractor,
        }]
    }

    result = client.request("contractors/add", data=data)
    logger.info("create_contractor odpowiedz wFirma: %s", result)
    contractors = result.get("contractors", [])

    if not contractors:
        raise WFirmaError("wFirma nie zwrocil danych kontrahenta", details=result)

    # wFirma zwraca dict z numerycznym kluczem lub liste
    if isinstance(contractors, list):
        new_contractor = contractors[0].get("contractor", {})
    else:
        first_key = next((k for k in sorted(contractors) if k != "parameters"), None)
        new_contractor = contractors[first_key].get("contractor", {}) if first_key else {}
    contractor_id = new_contractor.get("id")

    logger.info("Utworzono kontrahenta wFirma: %s (id=%s)", name, contractor_id)

    return {
        "contractor_id": contractor_id,
        "name": name,
    }


def find_or_create_contractor(
    client: WFirmaClient,
    *,
    name: str,
    street: str = "",
    zip_code: str = "",
    city: str = "",
    country: str = "PL",
    nip: Optional[str] = None,
    email: Optional[str] = None,
    phone: Optional[str] = None,
) -> int:
    """
    Znajdz istniejacego kontrahenta lub utworz nowego.

    Szuka po NIP (jesli podany) lub nazwie. Jesli nie znajdzie - tworzy.

    Returns
    -------
    int
        ID kontrahenta w wFirma.
    """
    logger.info("find_or_create_contractor: name=%r, nip=%r, street=%r, zip=%r, city=%r",
                name, nip, street, zip_code, city)
    existing = find_contractor(client, nip=nip, name=name)
    if existing:
        logger.info("Uzyto istniejacego kontrahenta id=%s dla %r", existing["id"], name)
        return existing["id"]

    logger.info("Nie znaleziono kontrahenta %r, tworze nowego", name)
    result = create_contractor(
        client,
        name=name,
        street=street,
        zip_code=zip_code,
        city=city,
        country=country,
        nip=nip,
        email=email,
        phone=phone,
    )
    return result["contractor_id"]
