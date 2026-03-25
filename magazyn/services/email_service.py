"""
Serwis email do klienta - transakcyjne wiadomosci HTML.

Obsluguje: potwierdzenie zamowienia, wyslanie przesylki,
fakture (z PDF w zalaczniku) i potwierdzenie dostawy.
Kazdy email zawiera link do personalizowanej strony zamowienia.
"""

import logging
import smtplib
from email.message import EmailMessage
from email.utils import formataddr

from flask import render_template

from ..config import settings
from ..db import get_session
from ..models import Order, OrderProduct
from ..orders import _get_tracking_url

logger = logging.getLogger(__name__)


def _get_order_page_url(token: str) -> str:
    """Zbuduj URL strony zamowienia klienta."""
    base = getattr(settings, "APP_BASE_URL", "") or ""
    base = base.rstrip("/")
    if not base:
        return ""
    return f"{base}/zamowienie/{token}"


def _send_html_email(
    to_email: str,
    subject: str,
    html_body: str,
    attachment: bytes | None = None,
    attachment_filename: str | None = None,
) -> bool:
    """Wyslij email HTML przez SMTP."""
    smtp_server = getattr(settings, "SMTP_SERVER", "") or ""
    if not smtp_server or not to_email:
        logger.warning(
            "Brak konfiguracji SMTP lub adresu odbiorcy - email nie wyslany"
        )
        return False

    smtp_port = int(getattr(settings, "SMTP_PORT", 0) or 587)
    smtp_user = getattr(settings, "SMTP_USERNAME", "") or ""
    smtp_pass = getattr(settings, "SMTP_PASSWORD", "") or ""
    from_name = getattr(settings, "EMAIL_FROM_NAME", "") or "Retriever Shop"
    from_addr = smtp_user or "noreply@retrievershop.pl"

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((from_name, from_addr))
    msg["To"] = to_email
    msg["Reply-To"] = from_addr

    # Wersja tekstowa jako fallback
    msg.set_content("Otworz wiadomosc w kliencie obslugujacym HTML.")
    msg.add_alternative(html_body, subtype="html")

    if attachment and attachment_filename:
        maintype = "application"
        subtype = "pdf"
        if attachment_filename.endswith(".pdf"):
            maintype, subtype = "application", "pdf"
        msg.add_attachment(
            attachment,
            maintype=maintype,
            subtype=subtype,
            filename=attachment_filename,
        )

    try:
        if smtp_port == 465:
            with smtplib.SMTP_SSL(smtp_server, smtp_port) as smtp:
                if smtp_user:
                    smtp.login(smtp_user, smtp_pass)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(smtp_server, smtp_port) as smtp:
                smtp.ehlo()
                smtp.starttls()
                smtp.ehlo()
                if smtp_user:
                    smtp.login(smtp_user, smtp_pass)
                smtp.send_message(msg)
        logger.info("Email wyslany do %s: %s", to_email, subject)
        return True
    except Exception as exc:
        logger.error("Blad wysylki email do %s: %s", to_email, exc)
        return False


def _load_order_context(order):
    """Przygotuj wspolny kontekst danych zamowienia do szablonow email."""
    products = []
    for op in order.products:
        price = float(op.price_brutto) if op.price_brutto else 0
        products.append({
            "name": op.name or "Produkt",
            "quantity": op.quantity or 1,
            "price": price,
            "attributes": op.attributes,
        })
    products_total = sum(p["price"] * p["quantity"] for p in products)
    delivery_cost = float(order.delivery_price) if order.delivery_price else 0
    order_total = products_total + delivery_cost

    order_page_url = ""
    if order.customer_token:
        order_page_url = _get_order_page_url(order.customer_token)

    # Skrocony ID zamowienia do wyswietlenia
    oid = order.order_id or ""
    display_id = oid[:20] + "..." if len(oid) > 20 else oid

    return {
        "order_id": display_id,
        "products": products,
        "products_total": products_total,
        "delivery_cost": delivery_cost,
        "order_total": order_total,
        "order_page_url": order_page_url,
        "delivery_method": order.delivery_method or "",
    }


def send_order_confirmation(order) -> bool:
    """Wyslij email z potwierdzeniem zamowienia."""
    email = order.email
    if not email:
        logger.debug(
            "Brak adresu email dla zamowienia %s - pomijam", order.order_id
        )
        return False

    ctx = _load_order_context(order)
    html = render_template("emails/order_confirmation.html", **ctx)
    return _send_html_email(
        to_email=email,
        subject=f"Potwierdzenie zamowienia #{ctx['order_id']} - Retriever Shop",
        html_body=html,
    )


def send_shipment_notification(order) -> bool:
    """Wyslij email o nadaniu przesylki."""
    email = order.email
    if not email:
        return False

    tracking_number = order.delivery_package_nr
    if not tracking_number:
        logger.debug(
            "Brak numeru przesylki dla %s - pomijam email", order.order_id
        )
        return False

    tracking_url = None
    try:
        tracking_url = _get_tracking_url(
            order.courier_code,
            order.delivery_package_module,
            tracking_number,
            order.delivery_method,
        )
    except Exception:
        pass

    ctx = _load_order_context(order)
    ctx["tracking_number"] = tracking_number
    ctx["tracking_url"] = tracking_url
    ctx["carrier"] = order.delivery_method or ""

    html = render_template("emails/shipment_notification.html", **ctx)
    return _send_html_email(
        to_email=email,
        subject=f"Przesylka nadana - zamowienie #{ctx['order_id']} - Retriever Shop",
        html_body=html,
    )


def send_invoice_email(
    order, pdf_data: bytes | None = None, pdf_filename: str | None = None
) -> bool:
    """Wyslij email z faktura (opcjonalnie z PDF w zalaczniku)."""
    email = order.email
    if not email:
        return False

    ctx = _load_order_context(order)

    invoice_data = None
    if order.want_invoice:
        invoice_data = {
            "company": order.invoice_company,
            "nip": order.invoice_nip,
            "name": order.invoice_fullname,
            "address": order.invoice_address,
            "city": order.invoice_city,
            "postcode": order.invoice_postcode,
        }
    ctx["invoice_data"] = invoice_data

    html = render_template("emails/invoice_email.html", **ctx)
    return _send_html_email(
        to_email=email,
        subject=f"Faktura do zamowienia #{ctx['order_id']} - Retriever Shop",
        html_body=html,
        attachment=pdf_data,
        attachment_filename=pdf_filename,
    )


def send_delivery_confirmation(order) -> bool:
    """Wyslij email o dostarczeniu przesylki."""
    email = order.email
    if not email:
        return False

    ctx = _load_order_context(order)
    html = render_template("emails/delivery_confirmation.html", **ctx)
    return _send_html_email(
        to_email=email,
        subject=f"Zamowienie #{ctx['order_id']} dostarczone - Retriever Shop",
        html_body=html,
    )


def send_invoice_correction(
    order,
    reason: str = "",
    refund_amount: float | None = None,
    pdf_data: bytes | None = None,
    pdf_filename: str | None = None,
    invoice_number: str = "",
) -> bool:
    """Wyslij email z korekta faktury (odpowiednik automatyzacji BL 90895)."""
    email = order.email
    if not email:
        return False

    ctx = _load_order_context(order)
    ctx["reason"] = reason
    ctx["refund_amount"] = refund_amount
    ctx["invoice_number"] = invoice_number

    html = render_template("emails/invoice_correction.html", **ctx)
    return _send_html_email(
        to_email=email,
        subject=f"Korekta za zamowienie nr {ctx['order_id']}",
        html_body=html,
        attachment=pdf_data,
        attachment_filename=pdf_filename,
    )


def send_refund_notification(
    order,
    reason: str = "",
    refund_amount: float | None = None,
    items: list | None = None,
) -> bool:
    """Wyslij email z potwierdzeniem zwrotu pieniedzy (bez korekty faktury)."""
    email = order.email
    if not email:
        return False

    ctx = _load_order_context(order)
    ctx["reason"] = reason
    ctx["refund_amount"] = refund_amount
    ctx["items"] = items or []

    html = render_template("emails/refund_notification.html", **ctx)
    return _send_html_email(
        to_email=email,
        subject=f"Potwierdzenie zwrotu - zamowienie #{ctx['order_id']} - Retriever Shop",
        html_body=html,
    )
