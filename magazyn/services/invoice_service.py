"""
Orkiestracja faktur: wFirma + Allegro + email.

Pelny przeplywy:
1. Utworz kontrahenta w wFirma (find_or_create)
2. Wystaw fakture VAT w wFirma
3. Pobierz PDF faktury
4. Upload PDF do zamowienia Allegro
5. Wyslij email do klienta z PDF w zalaczniku
6. Zapisz dane faktury w bazie (wfirma_invoice_id, wfirma_invoice_number)
"""
import json
import logging

from ..db import get_session
from ..models import Order

logger = logging.getLogger(__name__)


def generate_and_send_invoice(order_id: str) -> dict:
    """
    Pelny flow wystawienia faktury dla zamowienia.

    Returns
    -------
    dict
        {"success": bool, "invoice_number": str, "errors": list[str]}
    """
    from ..wfirma_api import WFirmaClient, create_invoice, download_invoice_pdf, find_or_create_contractor
    from ..allegro_api.invoices import upload_invoice_to_allegro
    from .email_service import send_invoice_email

    result = {"success": False, "invoice_number": None, "errors": []}

    with get_session() as db:
        order = db.query(Order).filter(Order.order_id == order_id).first()
        if not order:
            result["errors"].append(f"Zamowienie {order_id} nie znalezione")
            return result

        # Sprawdz czy faktura juz wystawiona
        if order.wfirma_invoice_id:
            result["errors"].append(
                f"Faktura juz wystawiona: {order.wfirma_invoice_number} "
                f"(id={order.wfirma_invoice_id})"
            )
            return result

        # Przygotuj dane kontrahenta
        contractor_name = (
            order.invoice_company
            or order.invoice_fullname
            or order.customer_name
            or ""
        )
        if not contractor_name:
            result["errors"].append("Brak danych kontrahenta (nazwa/firma)")
            return result

        # Przygotuj pozycje faktury
        items = []
        for op in order.products:
            price = float(op.price_brutto) if op.price_brutto else 0
            if price <= 0:
                continue
            items.append({
                "name": op.name or "Produkt",
                "unit": "szt.",
                "count": op.quantity or 1,
                "price": price,
                "vat": "zw",
            })

        if not items:
            result["errors"].append("Brak pozycji do zafakturowania")
            return result

        # Dodaj koszt dostawy jesli > 0
        delivery_price = float(order.delivery_price or 0)
        if delivery_price > 0:
            items.append({
                "name": f"Dostawa: {order.delivery_method or 'przesylka'}",
                "unit": "szt.",
                "count": 1,
                "price": delivery_price,
                "vat": "zw",
            })

        try:
            client = WFirmaClient.from_settings()
        except Exception as exc:
            result["errors"].append(f"Blad inicjalizacji klienta wFirma: {exc}")
            return result

        # 1. Znajdz/utworz kontrahenta
        try:
            contractor_id = find_or_create_contractor(
                client,
                name=contractor_name,
                street=order.invoice_address or order.delivery_address or "",
                zip_code=order.invoice_postcode or order.delivery_postcode or "",
                city=order.invoice_city or order.delivery_city or "",
                country=order.invoice_country or "PL",
                nip=order.invoice_nip or None,
                email=order.email or None,
                phone=order.phone or None,
            )
        except Exception as exc:
            result["errors"].append(f"Blad tworzenia kontrahenta wFirma: {exc}")
            return result

        # 2. Wystaw fakture
        try:
            inv = create_invoice(
                client,
                contractor_id=contractor_id,
                items=items,
                payment_method="transfer",
                invoice_type="bill",
                description=f"Zamowienie {order_id}",
            )
            invoice_id = inv["invoice_id"]
            invoice_number = inv["invoice_number"]
            result["invoice_number"] = invoice_number
        except Exception as exc:
            result["errors"].append(f"Blad wystawienia faktury wFirma: {exc}")
            return result

        # 3. Pobierz PDF
        pdf_data = None
        try:
            pdf_data = download_invoice_pdf(client, invoice_id)
        except Exception as exc:
            result["errors"].append(f"Blad pobierania PDF faktury: {exc}")
            # Kontynuuj - faktura wystawiona, ale PDF niedostepny

        # 4. Upload do Allegro (jesli zamowienie z Allegro i mamy PDF)
        if pdf_data and order.external_order_id:
            try:
                upload_invoice_to_allegro(
                    checkout_form_id=order.external_order_id,
                    invoice_number=invoice_number,
                    pdf_data=pdf_data,
                )
            except Exception as exc:
                logger.warning(
                    "Blad uploadu faktury do Allegro dla %s: %s",
                    order_id, exc,
                )
                # Nie blokuj dalszego flow - Allegro upload to nice-to-have

        # 5. Zapisz dane faktury w bazie
        order.wfirma_invoice_id = invoice_id
        order.wfirma_invoice_number = invoice_number
        db.commit()

        # 6. Wyslij email z PDF
        pdf_filename = None
        if pdf_data and invoice_number:
            safe_nr = invoice_number.replace("/", "_").replace("\\", "_")
            pdf_filename = f"{safe_nr}.pdf"

        try:
            sent = send_invoice_email(
                order,
                pdf_data=pdf_data,
                pdf_filename=pdf_filename,
            )
            if sent:
                _mark_email_sent(db, order, "invoice")
                db.commit()
        except Exception as exc:
            result["errors"].append(f"Blad wysylki email z faktura: {exc}")

        result["success"] = True
        logger.info(
            "Faktura %s wystawiona dla zamowienia %s (wFirma id=%s)",
            invoice_number, order_id, invoice_id,
        )

    return result


def _mark_email_sent(db, order, email_type: str):
    """Oznacz dany typ emaila jako wyslany."""
    sent = {}
    if order.emails_sent:
        try:
            sent = json.loads(order.emails_sent)
        except (json.JSONDecodeError, TypeError):
            sent = {}
    sent[email_type] = True
    order.emails_sent = json.dumps(sent)


def _was_email_sent(order, email_type: str) -> bool:
    """Sprawdz czy dany typ emaila juz zostal wyslany."""
    if not order.emails_sent:
        return False
    try:
        sent = json.loads(order.emails_sent)
        return sent.get(email_type, False)
    except (json.JSONDecodeError, TypeError):
        return False


def generate_correction_invoice(
    order_id: str,
    reason: str = "",
    return_id: int = None,
    include_delivery: bool = False,
) -> dict:
    """
    Wystaw korekte do faktury zamowienia na podstawie zwrotu.

    Jesli return_id jest podane, koryguje tylko pozycje ze zwrotu.
    Jesli return_id jest None, tworzy korekte zerujaca (wszystkie pozycje).

    Parameters
    ----------
    order_id : str
        ID zamowienia.
    reason : str
        Powod korekty.
    return_id : int, optional
        ID rekordu Return. Jesli podane, korygowane sa tylko zwracane pozycje.
    include_delivery : bool
        Czy uwzglednic korekte kosztu dostawy. Domyslnie False.

    Returns
    -------
    dict
        {"success": bool, "invoice_number": str, "errors": list[str]}
    """
    from ..wfirma_api import WFirmaClient
    from ..wfirma_api.invoices import (
        create_correction_invoice, download_invoice_pdf, get_invoice,
    )
    from ..models import Return
    from .email_service import send_invoice_correction

    result = {"success": False, "invoice_number": None, "errors": []}

    with get_session() as db:
        order = db.query(Order).filter(Order.order_id == order_id).first()
        if not order:
            result["errors"].append(f"Zamowienie {order_id} nie znalezione")
            return result

        if not order.wfirma_invoice_id:
            result["errors"].append(
                f"Zamowienie {order_id} nie ma wystawionej faktury wFirma"
            )
            return result

        try:
            client = WFirmaClient.from_settings()
        except Exception as exc:
            result["errors"].append(f"Blad inicjalizacji klienta wFirma: {exc}")
            return result

        original_invoice_id = int(order.wfirma_invoice_id)

        # Przygotuj corrected_items na podstawie zwrotu
        corrected_items = None
        if return_id is not None:
            return_record = db.query(Return).filter(Return.id == return_id).first()
            if not return_record:
                result["errors"].append(f"Zwrot id={return_id} nie znaleziony")
                return result

            return_items = json.loads(return_record.items_json) if return_record.items_json else []
            if not return_items:
                result["errors"].append(f"Zwrot id={return_id} nie ma pozycji")
                return result

            # Pobierz oryginalna fakture i dopasuj pozycje
            try:
                original = get_invoice(client, original_invoice_id)
            except Exception as exc:
                result["errors"].append(f"Blad pobrania oryginalnej faktury: {exc}")
                return result

            corrected_items, match_errors = _match_return_to_invoice(
                return_items, original, include_delivery=include_delivery,
            )
            result["errors"].extend(match_errors)

            if not corrected_items:
                result["errors"].append(
                    "Nie udalo sie dopasowac zadnej pozycji zwrotu do faktury"
                )
                return result

        if not reason:
            if return_id is not None:
                reason = f"Zwrot produktow z zamowienia {order_id}"
            else:
                reason = f"Korekta zerujaca do zamowienia {order_id}"

        try:
            inv = create_correction_invoice(
                client,
                original_invoice_id=original_invoice_id,
                corrected_items=corrected_items,
                description=reason,
            )
            invoice_id = inv["invoice_id"]
            invoice_number = inv["invoice_number"]
            result["invoice_number"] = invoice_number
        except Exception as exc:
            result["errors"].append(f"Blad wystawienia korekty wFirma: {exc}")
            return result

        # Zapisz korekte w zamowieniu
        order.wfirma_correction_id = invoice_id
        order.wfirma_correction_number = invoice_number
        db.commit()

        # Pobierz PDF korekty
        pdf_data = None
        try:
            pdf_data = download_invoice_pdf(client, invoice_id)
        except Exception as exc:
            result["errors"].append(f"Blad pobierania PDF korekty: {exc}")

        # Wyslij email z korekta
        if pdf_data:
            safe_nr = invoice_number.replace("/", "_").replace("\\", "_")
            pdf_filename = f"{safe_nr}.pdf"
            try:
                send_invoice_correction(
                    order,
                    reason=reason,
                    refund_amount=abs(inv["total"]),
                    pdf_data=pdf_data,
                    pdf_filename=pdf_filename,
                    invoice_number=invoice_number,
                )
                _mark_email_sent(db, order, "correction")
                db.commit()
            except Exception as exc:
                result["errors"].append(f"Blad wysylki korekty emailem: {exc}")

        result["success"] = True
        logger.info(
            "Korekta %s wystawiona dla zamowienia %s (wFirma id=%s)",
            invoice_number, order_id, invoice_id,
        )

    return result


def _match_return_to_invoice(
    return_items: list[dict],
    original_invoice: dict,
    include_delivery: bool = False,
) -> tuple[list[dict], list[str]]:
    """
    Dopasuj pozycje zwrotu do pozycji oryginalnej faktury wFirma.

    Dopasowanie odbywa sie po nazwie produktu. Zwracane pozycje
    ustawiaja count na (oryginalny count - zwracana ilosc).

    Parameters
    ----------
    return_items : list[dict]
        Pozycje ze zwrotu (items_json): [{"name": str, "quantity": int, ...}]
    original_invoice : dict
        Pelne dane faktury z wFirma (z invoicecontents).
    include_delivery : bool
        Czy uwzglednic korekte dostawy.

    Returns
    -------
    tuple[list[dict], list[str]]
        (corrected_items, ostrzezenia)
        corrected_items: [{"original_content_id": int, "count": int}]
    """
    errors = []

    # Wyciagnij pozycje faktury
    contents_data = original_invoice.get("invoicecontents", {})
    invoice_contents = []
    for k in sorted(contents_data):
        if k == "parameters":
            continue
        content = contents_data[k].get("invoicecontent", {})
        if content:
            invoice_contents.append(content)

    if not invoice_contents:
        errors.append("Oryginalna faktura nie ma pozycji")
        return [], errors

    # Buduj indeks nazw faktury (lowercase -> content)
    name_index = {}
    for content in invoice_contents:
        name_lower = content.get("name", "").strip().lower()
        if name_lower:
            name_index[name_lower] = content

    corrected_items = []
    for ret_item in return_items:
        ret_name = (ret_item.get("name") or "").strip()
        ret_qty = int(ret_item.get("quantity", 1))
        ret_name_lower = ret_name.lower()

        # Dokladne dopasowanie
        matched = name_index.get(ret_name_lower)

        # Jesli brak - szukaj czesciowego dopasowania
        if not matched:
            for inv_name_lower, content in name_index.items():
                if ret_name_lower in inv_name_lower or inv_name_lower in ret_name_lower:
                    matched = content
                    break

        if not matched:
            errors.append(
                f"Nie dopasowano pozycji zwrotu: '{ret_name}' "
                f"(brak na fakturze)"
            )
            continue

        original_count = int(float(matched.get("count", 0)))
        new_count = max(0, original_count - ret_qty)
        content_id = int(matched["id"])

        corrected_items.append({
            "original_content_id": content_id,
            "count": new_count,
        })

    # Korekta dostawy - znajdz pozycje "Dostawa:" na fakturze
    if include_delivery:
        for content in invoice_contents:
            name = content.get("name", "")
            if name.lower().startswith("dostawa"):
                content_id = int(content["id"])
                # Sprawdz czy nie jest juz w corrected_items
                if not any(ci["original_content_id"] == content_id for ci in corrected_items):
                    corrected_items.append({
                        "original_content_id": content_id,
                        "count": 0,
                    })
                break

    return corrected_items, errors
