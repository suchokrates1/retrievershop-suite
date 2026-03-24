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
                "vat": "23",
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
                "vat": "23",
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
