"""Orders blueprint - zarzadzanie zamowieniami."""
import json
import re
import secrets
import time
import logging
import unicodedata
from datetime import datetime, timedelta
from typing import Optional
from decimal import Decimal

from flask import Blueprint, render_template, abort, request, flash, redirect, url_for, current_app, after_this_request, send_file, jsonify
from sqlalchemy import desc, func, or_

from .auth import login_required
from .config import settings
from .db import get_session
from .models import Order, OrderProduct, OrderStatusLog, ProductSize, Product, PurchaseBatch, Return, ReturnStatusLog, AllegroOffer
from .settings_store import settings_store
from .services.order_detail_builder import (
    OrderDetailBuilder,
    build_order_detail_context,
)

logger = logging.getLogger(__name__)


def _strip_diacritics_ord(text: str) -> str:
    """Usun znaki diakrytyczne z tekstu (a -> a, n -> n, etc.)."""
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


# Mapowanie roznych form kolorow na klucz kanoniczny (ASCII, meski, mianownik)
_COLOR_CANONICAL_MAP = {
    "pomaranczowy": "pomaranczowy",
    "pomaranczowe": "pomaranczowy",
    "pomaranczowa": "pomaranczowy",
    "brazowy": "brazowy",
    "brazowe": "brazowy",
    "brazowa": "brazowy",
    "zolty": "zolty",
    "zolte": "zolty",
    "zolta": "zolty",
    "czarny": "czarny",
    "czarne": "czarny",
    "czarna": "czarny",
    "czerwony": "czerwony",
    "czerwone": "czerwony",
    "czerwona": "czerwony",
    "niebieski": "niebieski",
    "niebieskie": "niebieski",
    "niebieska": "niebieski",
    "zielony": "zielony",
    "zielone": "zielony",
    "zielona": "zielony",
    "rozowy": "rozowy",
    "rozowe": "rozowy",
    "rozowa": "rozowy",
    "fioletowy": "fioletowy",
    "fioletowe": "fioletowy",
    "fioletowa": "fioletowy",
    "srebrny": "srebrny",
    "srebrne": "srebrny",
    "srebrna": "srebrny",
    "granatowy": "granatowy",
    "granatowe": "granatowy",
    "granatowa": "granatowy",
    "szary": "szary",
    "szare": "szary",
    "szara": "szary",
    "turkusowy": "turkusowy",
    "turkusowe": "turkusowy",
    "turkusowa": "turkusowy",
    "bialy": "bialy",
    "biale": "bialy",
    "biala": "bialy",
    "blekitny": "blekitny",
    "blekitne": "blekitny",
    "blekitna": "blekitny",
    "limonkowy": "limonkowy",
    "limonkowe": "limonkowy",
    "limonkowa": "limonkowy",
}


def _normalize_color_key(color: str) -> str:
    """Normalizuj kolor do klucza kanonicznego (ASCII, meski, mianownik)."""
    if not color:
        return ""
    stripped = _strip_diacritics_ord(color).lower().strip()
    return _COLOR_CANONICAL_MAP.get(stripped, stripped)


def _extract_series_from_name(product_name: str) -> str:
    """Wyciagnij nazwe serii z pelnej nazwy produktu."""
    if not product_name:
        return ""
    match = re.search(r'Truelove\s+(.+)', product_name, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return product_name


def _match_product_to_warehouse(db, name: str, color: str, size: str):
    """Dopasuj produkt z zamowienia do ProductSize w magazynie.

    Uzywa ekstrakcji serii z nazwy i normalizacji kolorow
    (strip diacritics + kanonizacja formy gramatycznej).
    """
    series = _extract_series_from_name(name)
    if not series:
        return None

    series_norm = _strip_diacritics_ord(series).lower()
    color_norm = _normalize_color_key(color)

    # Normalizacja rozmiaru (np. "Xl" -> "XL")
    size_upper = size.upper() if size else size
    candidates = (
        db.query(ProductSize)
        .join(Product)
        .filter(func.upper(ProductSize.size) == size_upper)
        .all()
    )

    for ps in candidates:
        product = ps.product
        db_series = _strip_diacritics_ord(product.series or "").lower()
        db_color = _normalize_color_key(product.color or "")

        if series_norm == db_series and color_norm == db_color:
            return ps

    # Fallback: proba dopasowania z contains
    for ps in candidates:
        product = ps.product
        db_series = _strip_diacritics_ord(product.series or "").lower()
        db_color = _normalize_color_key(product.color or "")

        if (db_series and (db_series in series_norm or series_norm in db_series)
                and color_norm == db_color):
            return ps

    # Fallback 2: brak koloru w zamowieniu - dopasowanie po serii + nazwie produktu
    if not color_norm:
        series_matches = []
        for ps in candidates:
            product = ps.product
            db_series = _strip_diacritics_ord(product.series or "").lower()
            if db_series and (series_norm == db_series
                    or db_series in series_norm
                    or series_norm in db_series):
                # Dodatkowa weryfikacja: nazwa produktu musi pasowac do nazwy z zamowienia
                db_name_norm = _strip_diacritics_ord(product.name or "").lower()
                name_norm = _strip_diacritics_ord(name or "").lower()
                if db_name_norm == name_norm or db_name_norm in name_norm or name_norm in db_name_norm:
                    series_matches.append(ps)
        if len(series_matches) == 1:
            return series_matches[0]

    return None


bp = Blueprint("orders", __name__)


# All valid statuses for the system
# Flow: pobrano → wydrukowano → spakowano → przekazano_kurierowi → w_drodze → w_punkcie → gotowe_do_odbioru → dostarczono → zakończono
VALID_STATUSES = [
    # Etap wewnętrzny (magazyn)
    "pobrano",              # Pobrano zamowienie
    "niewydrukowano",       # Niewydrukowano (legacy)
    "wydrukowano",          # Wydrukowano etykietę
    "spakowano",            # Spakowano
    
    # Etap przekazania
    "przekazano_kurierowi", # Przekazano kurierowi/paczkomatowi
    
    # Etap transportu (z Allegro API)
    "w_drodze",             # W tranzycie
    "w_punkcie",            # W punkcie odbioru (paczkomat)
    "gotowe_do_odbioru",    # Gotowe do odbioru (paczkomat/punkt)
    
    # Finał
    "dostarczono",          # Doręczono klientowi
    "zakończono",           # Zakończono (archiwum)
    
    # Problemy
    "niedostarczono",       # Nieudane doręczenie
    "zwrot",                # Zwrot
    "anulowano",            # Anulowano
]

# Hierarchia statusów - statusy mogą się tylko przesuwać "do przodu"
# Im wyższy indeks, tym bardziej zaawansowany status
# Statusy problemowe (niedostarczono, zwrot, anulowano) można ustawić zawsze
STATUS_HIERARCHY = {
    "pobrano": 0,
    "niewydrukowano": 1,
    "wydrukowano": 2,
    "spakowano": 3,
    "przekazano_kurierowi": 4,
    "w_drodze": 5,
    "w_punkcie": 6,
    "gotowe_do_odbioru": 7,
    "dostarczono": 8,
    "zakończono": 9,
    # Statusy problemowe - mogą być ustawione w każdym momencie
    "niedostarczono": 999,
    "zwrot": 999,
    "anulowano": 999,
}

# SHIPPING_STAGES i RETURN_STAGES przeniesione do services/order_detail_builder.py


def _unix_to_datetime(timestamp: Optional[int]) -> Optional[datetime]:
    """Convert Unix timestamp to datetime."""
    if timestamp:
        try:
            return datetime.fromtimestamp(timestamp)
        except (ValueError, OSError):
            pass
    return None


def _get_status_display(status: str) -> tuple[str, str]:
    """Return (display text, badge class) for status.
    
    Flow statusów wysyłki:
    pobrano → wydrukowano → spakowano → przekazano_kurierowi → w_drodze → gotowe_do_odbioru → dostarczono → zakończono
    """
    STATUS_MAP = {
        # Etap wewnętrzny (magazyn)
        "pobrano": ("Pobrano", "bg-light text-dark"),
        "niewydrukowano": ("Niewydrukowano", "bg-secondary"),
        "wydrukowano": ("Wydrukowano", "bg-info"),
        "spakowano": ("Spakowano", "bg-info"),
        
        # Etap przekazania
        "przekazano_kurierowi": ("Przekazano kurierowi", "bg-primary"),
        
        # Etap transportu (z Allegro API)
        "w_drodze": ("W drodze", "bg-warning text-dark"),
        "gotowe_do_odbioru": ("Do odbioru", "bg-info"),
        "awizo": ("Awizo", "bg-warning text-dark"),
        
        # Finał
        "dostarczono": ("Dostarczono", "bg-success"),
        "zakończono": ("Zakończono", "bg-success"),
        
        # Problemy
        "niedostarczono": ("Niedostarczono", "bg-danger"),
        "zwrot": ("Zwrot", "bg-danger"),
        "zagubiono": ("Zagubiono", "bg-danger"),
        "anulowano": ("Anulowano", "bg-dark"),
    }
    return STATUS_MAP.get(status, (status, "bg-secondary"))


def _get_tracking_url(courier_code: Optional[str], delivery_package_module: Optional[str], tracking_number: Optional[str], delivery_method: Optional[str] = None) -> Optional[str]:
    """
    Generate tracking URL based on courier info and tracking number.
    
    UWAGA: Allegro Smart (One Box, Orlen Paczka) używa różnych przewoźników.
    Nie ma uniwersalnego URL - każda przesyłka wymaga sprawdzenia przez API Allegro
    lub ma dedykowany URL przewoźnika.
    """
    if not tracking_number:
        return None
    
    # Normalize courier identifiers
    courier_text = f"{courier_code or ''} {delivery_package_module or ''} {delivery_method or ''}".lower()
    
    # Debug logging
    current_app.logger.debug(f"_get_tracking_url: courier_text='{courier_text}' tracking_number={tracking_number}")
    
    # Courier tracking URL patterns
    # Zwraca None dla kurierów bez publicznego śledzenia (np. Allegro Smart, Orlen Paczka)
    TRACKING_URLS = {
        # InPost Paczkomaty
        "inpost": f"https://inpost.pl/sledzenie-przesylek?number={tracking_number}",
        "paczkomat": f"https://inpost.pl/sledzenie-przesylek?number={tracking_number}",
        
        # DPD  
        "dpd": f"https://tracktrace.dpd.com.pl/parcelDetails?typ=1&p1={tracking_number}",
        
        # Poczta Polska / Pocztex
        "pocztex": f"https://emonitoring.poczta-polska.pl/?numer={tracking_number}",
        "poczta": f"https://emonitoring.poczta-polska.pl/?numer={tracking_number}",
        
        # DHL
        "dhl": f"https://www.dhl.com/pl-pl/home/tracking.html?tracking-id={tracking_number}",
        
        # UPS
        "ups": f"https://www.ups.com/track?tracknum={tracking_number}",
        
        # FedEx
        "fedex": f"https://www.fedex.com/fedextrack/?tracknumbers={tracking_number}",
        
        # GLS
        "gls": f"https://gls-group.com/PL/pl/sledzenie-paczek?match={tracking_number}",
        
        # Orlen Paczka - BRAK publicznego URL śledzenia
        # Wymaga aplikacji mobilnej lub panelu Allegro - zwracamy None
        "orlen": None,
        
        # Allegro Smart (One Box, One Kurier, One Punkt) - BRAK publicznego URL
        # Śledzenie tylko przez panel Allegro - zwracamy None
        "allegro": None,
    }
    
    # Try to match courier - zwróć None jeśli brak publicznego URL
    for key, url in TRACKING_URLS.items():
        if key in courier_text:
            current_app.logger.debug(f"_get_tracking_url: Matched '{key}' -> {url or 'NO_PUBLIC_URL'}")
            return url  # Może być None dla kurierów bez publicznego śledzenia
    
    # Default: return None if courier not recognized
    current_app.logger.debug(f"_get_tracking_url: No match found for courier_text='{courier_text}'")
    return None


@bp.route("/orders")
@login_required
def orders_list():
    """Display paginated list of orders with filtering and sorting."""
    # Note: Automatic sync runs every hour via order_sync_scheduler
    
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 10, type=int)
    search = request.args.get("search", "").strip()
    sort_by = request.args.get("sort", "date")  # date, order_id, status, amount
    sort_dir = request.args.get("dir", "desc")  # asc, desc
    status_filter = request.args.get("status", "all")
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()
    
    # Limit per_page to reasonable values
    if per_page not in [10, 25, 50, 100]:
        per_page = 10
    
    with get_session() as db:
        query = db.query(Order)
        
        # Apply search filter - szuka rowniez w produktach zamowienia
        if search:
            search_pattern = f"%{search}%"
            # Subquery: zamowienia zawierajace pasujacy produkt
            product_match_subq = db.query(OrderProduct.order_id).filter(
                OrderProduct.name.ilike(search_pattern)
            ).distinct().subquery()
            
            query = query.filter(
                or_(
                    Order.order_id.ilike(search_pattern),
                    Order.external_order_id.ilike(search_pattern),
                    Order.customer_name.ilike(search_pattern),
                    Order.email.ilike(search_pattern),
                    Order.phone.ilike(search_pattern),
                    Order.delivery_method.ilike(search_pattern),
                    Order.order_id.in_(product_match_subq),
                )
            )

        # Date range filter (date_add jest unix timestamp)
        if date_from:
            try:
                dt_from = datetime.strptime(date_from, "%Y-%m-%d")
                query = query.filter(Order.date_add >= int(dt_from.timestamp()))
            except ValueError:
                pass
        if date_to:
            try:
                dt_to = datetime.strptime(date_to, "%Y-%m-%d")
                # Koniec dnia = poczatek nastepnego
                dt_to_end = dt_to + timedelta(days=1)
                query = query.filter(Order.date_add < int(dt_to_end.timestamp()))
            except ValueError:
                pass

        # Status filter - filtruj po ostatnim statusie
        if status_filter and status_filter != "all":
            # Subquery: najnowszy status dla kazdego zamowienia
            latest_status_subq = (
                db.query(
                    OrderStatusLog.order_id,
                    func.max(OrderStatusLog.timestamp).label("max_ts")
                )
                .group_by(OrderStatusLog.order_id)
                .subquery()
            )
            # Dolacz najnowszy status
            query = query.join(
                latest_status_subq,
                Order.order_id == latest_status_subq.c.order_id,
            ).join(
                OrderStatusLog,
                (OrderStatusLog.order_id == latest_status_subq.c.order_id) &
                (OrderStatusLog.timestamp == latest_status_subq.c.max_ts),
            )
            if status_filter == "w_realizacji":
                query = query.filter(OrderStatusLog.status.in_([
                    "pobrano", "wydrukowano", "spakowano",
                ]))
            elif status_filter == "w_transporcie":
                query = query.filter(OrderStatusLog.status.in_([
                    "przekazano_kurierowi", "w_drodze", "gotowe_do_odbioru", "awizo",
                ]))
            elif status_filter == "zakonczone":
                query = query.filter(OrderStatusLog.status.in_([
                    "dostarczono", "zakończono",
                ]))
            elif status_filter == "problem":
                query = query.filter(OrderStatusLog.status.in_([
                    "niedostarczono", "zwrot", "zagubiono", "anulowano",
                ]))
            else:
                # Bezposredni status
                query = query.filter(OrderStatusLog.status == status_filter)
        
        # Apply sorting
        if sort_by == "order_id":
            sort_col = Order.date_add  # LP sortuje chronologicznie
        elif sort_by == "amount":
            sort_col = Order.payment_done
        else:  # default: date
            sort_col = Order.date_add
        
        if sort_dir == "asc":
            query = query.order_by(sort_col.asc())
        else:
            query = query.order_by(sort_col.desc())
        
        # Pagination
        total = query.count()
        orders = query.offset((page - 1) * per_page).limit(per_page).all()
        
        # Oblicz LP chronologiczne dla kazdego zamowienia
        # LP = numer porzadkowy od najstarszego zamowienia (1 = najstarsze)
        if search:
            # Przy wyszukiwaniu: LP wzgledem przefiltrowanego zbioru
            lp_base_q = db.query(Order.order_id)
            search_pattern_lp = f"%{search}%"
            product_match_subq_lp = db.query(OrderProduct.order_id).filter(
                OrderProduct.name.ilike(search_pattern_lp)
            ).distinct().subquery()
            lp_base_q = lp_base_q.filter(
                or_(
                    Order.order_id.ilike(search_pattern_lp),
                    Order.external_order_id.ilike(search_pattern_lp),
                    Order.customer_name.ilike(search_pattern_lp),
                    Order.email.ilike(search_pattern_lp),
                    Order.phone.ilike(search_pattern_lp),
                    Order.delivery_method.ilike(search_pattern_lp),
                    Order.order_id.in_(product_match_subq_lp),
                )
            )
            lp_ids = [r.order_id for r in lp_base_q.order_by(Order.date_add.asc()).all()]
        else:
            lp_ids = [r.order_id for r in db.query(Order.order_id).order_by(Order.date_add.asc()).all()]
        lp_map = {oid: idx + 1 for idx, oid in enumerate(lp_ids)}
        
        # Convert timestamps and add latest status
        orders_data = []
        for order in orders:
            # Get latest status
            latest_status = (
                db.query(OrderStatusLog)
                .filter(OrderStatusLog.order_id == order.order_id)
                .order_by(desc(OrderStatusLog.timestamp))
                .first()
            )
            
            status_text, status_class = _get_status_display(
                latest_status.status if latest_status else "niewydrukowano"
            )
            
            # Get product summary
            products = db.query(OrderProduct).filter(
                OrderProduct.order_id == order.order_id
            ).all()
            product_summary = ", ".join([
                f"{p.name or 'Produkt'} x{p.quantity}"
                for p in products[:3]
            ])
            if len(products) > 3:
                product_summary += f" (+{len(products) - 3} wiecej)"
            
            # Sprawdz czy zamowienie ma aktywny zwrot
            has_return = db.query(Return).filter(
                Return.order_id == order.order_id,
                Return.status != "cancelled"
            ).first() is not None
            
            orders_data.append({
                "order_id": order.order_id,
                "lp": lp_map.get(order.order_id, 0),
                "external_order_id": order.external_order_id,
                "shop_order_id": order.shop_order_id,
                "customer_name": order.customer_name,
                "platform": order.platform,
                "date_add": _unix_to_datetime(order.date_add),
                "delivery_method": order.delivery_method,
                "payment_done": order.payment_done,
                "currency": order.currency,
                "status_text": status_text,
                "status_class": status_class,
                "product_summary": product_summary,
                "tracking_number": order.delivery_package_nr,
                "has_return": has_return,
            })
        
        # Calculate pagination
        total_pages = (total + per_page - 1) // per_page
        has_prev = page > 1
        has_next = page < total_pages
        
        return render_template(
            "orders_list.html",
            orders=orders_data,
            page=page,
            per_page=per_page,
            total_pages=total_pages,
            has_prev=has_prev,
            has_next=has_next,
            total=total,
            search=search,
            sort_by=sort_by,
            sort_dir=sort_dir,
            status_filter=status_filter,
            date_from=date_from,
            date_to=date_to,
        )


@bp.route("/order/<order_id>")
@login_required
def order_detail(order_id: str):
    """Display detailed view of a single order."""
    with get_session() as db:
        order = db.query(Order).filter(Order.order_id == order_id).first()
        if not order:
            abort(404)
        
        # Uzyj nowego serwisu do budowania kontekstu
        context = build_order_detail_context(db, order)
        
        # Dodaj dodatkowe dane potrzebne w szablonie
        context["date_add"] = _unix_to_datetime(order.date_add)
        context["date_confirmed"] = _unix_to_datetime(order.date_confirmed)
        context["tracking_url"] = _get_tracking_url(
            order.courier_code, 
            order.delivery_package_module, 
            order.delivery_package_nr, 
            order.delivery_method
        )

        # Komunikacja z klientem - log emaili
        import json as _json
        emails_sent = {}
        if order.emails_sent:
            try:
                emails_sent = _json.loads(order.emails_sent)
            except (ValueError, TypeError):
                pass

        email_types_map = {
            "confirmation": "Potwierdzenie zamowienia",
            "shipment": "Nadanie przesylki",
            "invoice": "Faktura",
            "delivery": "Potwierdzenie dostawy",
            "correction": "Korekta faktury",
        }
        email_log = [
            {"type": k, "label": email_types_map.get(k, k), "sent": True}
            for k in email_types_map
            if emails_sent.get(k)
        ]
        context["email_log"] = email_log
        context["emails_sent"] = emails_sent

        # Faktura wFirma
        context["wfirma_invoice_id"] = order.wfirma_invoice_id
        context["wfirma_invoice_number"] = order.wfirma_invoice_number

        # Link do strony zamowienia klienta
        customer_page_url = ""
        if order.customer_token:
            base = getattr(settings, "APP_BASE_URL", "") or ""
            base = base.rstrip("/")
            if base:
                customer_page_url = f"{base}/zamowienie/{order.customer_token}"
        context["customer_page_url"] = customer_page_url
        
        rendered = render_template("order_detail.html", **context)
        
        # Zapobiegaj cache przegladarki
        response = current_app.make_response(rendered)
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        return response


@bp.route("/order/<order_id>/invoice-pdf")
@login_required
def download_invoice_pdf(order_id: str):
    """Pobierz PDF faktury z wFirma."""
    with get_session() as db:
        order = db.query(Order).filter(Order.order_id == order_id).first()
        if not order or not order.wfirma_invoice_id:
            abort(404)

        try:
            from .wfirma_api import WFirmaClient
            from .wfirma_api import download_invoice_pdf as wfirma_download
            client = WFirmaClient.from_settings()
            pdf_data = wfirma_download(client, order.wfirma_invoice_id)
        except Exception as exc:
            logger.error("Blad pobierania PDF faktury %s: %s", order.wfirma_invoice_number, exc)
            flash("Blad pobierania PDF faktury", "error")
            return redirect(url_for(".order_detail", order_id=order_id))

        safe_nr = (order.wfirma_invoice_number or "faktura").replace("/", "_").replace("\\", "_")
        from flask import Response
        return Response(
            pdf_data,
            mimetype="application/pdf",
            headers={"Content-Disposition": f"inline; filename={safe_nr}.pdf"},
        )


@bp.route("/order/<order_id>/update_status", methods=["POST"])
@login_required
def update_order_status(order_id: str):
    """Update order status."""
    with get_session() as db:
        order = db.query(Order).filter(Order.order_id == order_id).first()
        if not order:
            abort(404)
        
        new_status = request.form.get("status")
        tracking_number = request.form.get("tracking_number", "").strip() or None
        courier_code = request.form.get("courier_code", "").strip() or None
        notes = request.form.get("notes", "").strip() or None
        
        if new_status not in VALID_STATUSES:
            flash("Nieprawidłowy status", "error")
            return redirect(url_for(".order_detail", order_id=order_id))
        
        # Create status log entry
        status_log = OrderStatusLog(
            order_id=order_id,
            status=new_status,
            tracking_number=tracking_number,
            courier_code=courier_code,
            notes=notes,
        )
        db.add(status_log)
        
        # Update order tracking info if provided
        if tracking_number:
            order.delivery_package_nr = tracking_number
        if courier_code:
            order.courier_code = courier_code
        
        db.commit()
        
        flash("Status zamówienia zaktualizowany", "success")
        return redirect(url_for(".order_detail", order_id=order_id))


@bp.route("/order/<order_id>/reprint", methods=["POST"])
@login_required
def reprint_label(order_id: str):
    """Reprint shipping label for an order."""
    from . import print_agent
    
    try:
        # Try to get packages and print labels
        packages = print_agent.get_order_packages(order_id)
        printed_any = False
        
        for pkg in packages:
            pid = pkg.get("shipment_id") or pkg.get("package_id")
            code = pkg.get("courier_code") or pkg.get("carrier_id") or ""
            if not pid:
                continue
            label_data, ext = print_agent.get_label(code, pid)
            if label_data:
                print_agent.print_label(label_data, ext, order_id)
                printed_any = True
        
        if printed_any:
            # Add status log entry
            with get_session() as db:
                add_order_status(db, order_id, "wydrukowano", notes="Reprint etykiety")
                db.commit()
            flash("Etykieta została wysłana do drukarki", "success")
        else:
            flash("Nie znaleziono etykiety do wydruku", "warning")
            
    except Exception as exc:
        flash(f"Błąd drukowania: {exc}", "error")
    
    # Redirect back to wherever the user came from
    referrer = request.referrer
    if referrer and "order" in referrer:
        return redirect(referrer)
    return redirect(url_for(".orders_list"))


@bp.route("/order/<order_id>/restore_return_stock", methods=["POST"])
@login_required
def restore_return_stock(order_id: str):
    """Recznie przywroc stan magazynowy dla zwrotu."""
    from .returns import restore_stock_for_return
    from .models import Return
    
    with get_session() as db:
        return_record = db.query(Return).filter(Return.order_id == order_id).first()
        
        if not return_record:
            flash(f"Nie znaleziono zwrotu dla zamowienia {order_id}", "error")
        elif return_record.stock_restored:
            flash("Stan juz zostal przywrocony", "warning")
        else:
            if restore_stock_for_return(return_record.id):
                flash("Stan magazynowy zostal przywrocony", "success")
            else:
                flash("Nie udalo sie przywrocic stanu - sprawdz czy produkty sa powiazane z magazynem", "error")
    
    return redirect(url_for(".order_detail", order_id=order_id))


@bp.route("/order/<order_id>/check_refund_eligibility", methods=["GET"])
@login_required
def check_refund_eligibility(order_id: str):
    """
    Sprawdz czy zamowienie kwalifikuje sie do zwrotu pieniedzy.
    
    Zwraca JSON z informacjami o kwocie i statusie.
    """
    from .returns import check_refund_eligibility as check_eligibility
    
    eligible, message, details = check_eligibility(order_id)
    
    return jsonify({
        "eligible": eligible,
        "message": message,
        "details": details
    })


@bp.route("/order/<order_id>/process_refund", methods=["POST"])
@login_required
def process_refund(order_id: str):
    """
    Przetworz zwrot pieniedzy dla zamowienia.
    
    UWAGA: Ta operacja jest NIEODWRACALNA!
    
    Wymaga potwierdzenia przez:
    1. Pole confirm=true w POST
    2. Pole allegro_return_id musi zgadzac sie z baza
    """
    from .returns import process_refund as do_refund, check_refund_eligibility as check_eligibility
    from .models import Return
    
    # Sprawdz czy potwierdzono operacje
    confirm = request.form.get("confirm") == "true" or request.json and request.json.get("confirm") == True
    if not confirm:
        flash("Operacja wymaga potwierdzenia", "error")
        return redirect(url_for(".order_detail", order_id=order_id))
    
    # Dodatkowa walidacja - sprawdz allegro_return_id
    expected_return_id = request.form.get("allegro_return_id") or (request.json and request.json.get("allegro_return_id"))
    
    with get_session() as db:
        return_record = db.query(Return).filter(Return.order_id == order_id).first()
        
        if not return_record:
            flash("Nie znaleziono zwrotu dla tego zamowienia", "error")
            return redirect(url_for(".order_detail", order_id=order_id))
        
        if return_record.allegro_return_id != expected_return_id:
            flash("Blad walidacji - ID zwrotu Allegro nie zgadza sie", "error")
            return redirect(url_for(".order_detail", order_id=order_id))
    
    # Sprawdz jeszcze raz kwalifikowalnosc
    eligible, check_message, _ = check_eligibility(order_id)
    if not eligible:
        flash(f"Zwrot nie kwalifikuje sie: {check_message}", "error")
        return redirect(url_for(".order_detail", order_id=order_id))
    
    # Opcjonalne parametry
    delivery_cost_covered = request.form.get("delivery_cost_covered", "true") == "true"
    reason = request.form.get("reason", "")
    
    # Wykonaj zwrot
    success, message = do_refund(
        order_id=order_id,
        delivery_cost_covered=delivery_cost_covered,
        reason=reason
    )
    
    if success:
        flash(f"Zwrot pieniedzy zainicjowany pomyslnie! {message}", "success")
    else:
        flash(f"Blad zwrotu pieniedzy: {message}", "error")
    
    return redirect(url_for(".order_detail", order_id=order_id))


@bp.route("/order/<order_id>/download_label", methods=["GET"])
@login_required
def download_label(order_id: str):
    """Download shipping label PDF for an order."""
    from . import print_agent
    import tempfile
    import os
    
    try:
        # Try to get packages and download first label
        packages = print_agent.get_order_packages(order_id)
        
        for pkg in packages:
            pid = pkg.get("shipment_id") or pkg.get("package_id")
            code = pkg.get("courier_code") or pkg.get("carrier_id") or ""
            if not pid:
                continue
            label_data, ext = print_agent.get_label(code, pid)
            if label_data:
                # Save to temporary file and send
                import base64
                pdf_bytes = base64.b64decode(label_data)
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext}")
                tmp.write(pdf_bytes)
                tmp.close()
                
                @after_this_request
                def remove_file(response):
                    try:
                        os.remove(tmp.name)
                    except Exception:
                        pass
                    return response
                
                return send_file(
                    tmp.name,
                    as_attachment=True,
                    download_name=f"etykieta_{order_id}.{ext}",
                    mimetype="application/pdf" if ext == "pdf" else "application/octet-stream"
                )
        
        flash("Nie znaleziono etykiety do pobrania", "warning")
            
    except Exception as exc:
        flash(f"Błąd pobierania etykiety: {exc}", "error")
    
    return redirect(url_for(".order_detail", order_id=order_id))


def sync_order_from_data(db, order_data: dict) -> Order:
    """
    Tworzy lub aktualizuje zamowienie na podstawie slownika danych.
    Uzywane przy synchronizacji z Allegro API oraz recznym dodawaniu zamowien.
    
    Deduplikacja: jesli zamowienie o danym external_order_id juz istnieje
    pod innym order_id, nie tworzymy duplikatu.
    """
    order_id = str(order_data.get("order_id"))
    external_order_id = order_data.get("external_order_id")
    
    # Check if order exists by order_id
    order = db.query(Order).filter(Order.order_id == order_id).first()
    is_new_order = False
    
    if not order:
        # Sprawdz czy zamowienie o tym external_order_id juz istnieje (z innego zrodla)
        if external_order_id:
            existing = db.query(Order).filter(
                Order.external_order_id == external_order_id
            ).first()
            if existing:
                # Zamowienie juz istnieje pod innym ID - aktualizuj istniejace
                order = existing
                is_new_order = False
        
        if not order:
            order = Order(order_id=order_id)
            order.customer_token = secrets.token_urlsafe(32)
            db.add(order)
            is_new_order = True
    
    # Po deduplikacji upewnij sie ze order_id odpowiada faktycznemu rekordowi w bazie
    order_id = order.order_id
    
    # Update all fields from order_data
    order.external_order_id = order_data.get("external_order_id")
    order.shop_order_id = order_data.get("shop_order_id")
    order.customer_name = order_data.get("customer") or order_data.get("delivery_fullname")
    order.email = order_data.get("email")
    order.phone = order_data.get("phone")
    order.user_login = order_data.get("user_login")
    order.platform = order_data.get("platform")
    order.order_source_id = order_data.get("order_source_id")
    order.order_status_id = order_data.get("order_status_id")
    order.confirmed = order_data.get("confirmed", False)
    order.date_add = order_data.get("date_add")
    order.date_confirmed = order_data.get("date_confirmed")
    order.date_in_status = order_data.get("date_in_status")
    order.delivery_method = order_data.get("shipping") or order_data.get("delivery_method")
    order.delivery_method_id = order_data.get("delivery_method_id")
    order.delivery_price = order_data.get("delivery_price")
    order.delivery_fullname = order_data.get("delivery_fullname")
    order.delivery_company = order_data.get("delivery_company")
    order.delivery_address = order_data.get("delivery_address")
    order.delivery_city = order_data.get("delivery_city")
    order.delivery_postcode = order_data.get("delivery_postcode")
    order.delivery_country = order_data.get("delivery_country")
    order.delivery_country_code = order_data.get("delivery_country_code")
    order.delivery_point_id = order_data.get("delivery_point_id")
    order.delivery_point_name = order_data.get("delivery_point_name")
    order.delivery_point_address = order_data.get("delivery_point_address")
    order.delivery_point_postcode = order_data.get("delivery_point_postcode")
    order.delivery_point_city = order_data.get("delivery_point_city")
    order.invoice_fullname = order_data.get("invoice_fullname")
    order.invoice_company = order_data.get("invoice_company")
    order.invoice_nip = order_data.get("invoice_nip")
    order.invoice_address = order_data.get("invoice_address")
    order.invoice_city = order_data.get("invoice_city")
    order.invoice_postcode = order_data.get("invoice_postcode")
    order.invoice_country = order_data.get("invoice_country")
    order.want_invoice = order_data.get("want_invoice") == "1"
    order.currency = order_data.get("currency", "PLN")
    order.payment_method = order_data.get("payment_method")
    cod_val = order_data.get("payment_method_cod")
    order.payment_method_cod = cod_val in ("1", True, 1)
    order.payment_done = order_data.get("payment_done")
    order.user_comments = order_data.get("user_comments")
    order.admin_comments = order_data.get("admin_comments")
    order.courier_code = order_data.get("courier_code")
    order.delivery_package_module = order_data.get("delivery_package_module")
    order.delivery_package_nr = order_data.get("delivery_package_nr")
    
    # Store raw products JSON
    products_list = order_data.get("products", [])
    order.products_json = json.dumps(products_list) if products_list else None

    # Korekcja payment_done dla zamowien za pobraniem (COD)
    # Allegro raportuje payment_done=0 dla COD, bo gotowka nie przechodzi
    # przez system platnosci online.
    if order.payment_method_cod and float(order.payment_done or 0) == 0:
        if order.order_status_id and int(order.order_status_id) == 91621:
            total_products = sum(
                float(p.get("price_brutto", 0)) * int(p.get("quantity", 1))
                for p in products_list
            )
            delivery = float(order.delivery_price or 0)
            order.payment_done = total_products + delivery
            logger.info(
                "Zamowienie COD %s doreczone - ustawiam payment_done=%.2f "
                "(produkty=%.2f + dostawa=%.2f)",
                order_id, order.payment_done, total_products, delivery
            )
    
    # Sync order products
    # First, remove existing products for this order
    db.query(OrderProduct).filter(OrderProduct.order_id == order_id).delete()
    
    for prod in products_list:
        ean = prod.get("ean", "").strip() or None
        
        # Try to link to warehouse product
        product_size_id = None
        ean_matched = False
        
        # 1. Try by EAN first (most reliable)
        if ean:
            ps = db.query(ProductSize).filter(ProductSize.barcode == ean).first()
            if ps:
                product_size_id = ps.id
                ean_matched = True
        
        # 2. If no EAN or EAN didn't match, try intelligent matching by name/color/size
        if not product_size_id:
            from .parsing import parse_product_info
            name, size, color = parse_product_info(prod)

            if name and size:
                ps = _match_product_to_warehouse(db, name, color, size)
                if ps:
                    product_size_id = ps.id
                    logger.info(f"Matched: {prod.get('name')} -> {name}/{color}/{size} -> product_size_id={ps.id}")
                else:
                    logger.warning(f"NOT MATCHED: {prod.get('name')} -> parsed: {name}/{color or '(brak)'}/{size}")
            else:
                logger.warning(f"NOT MATCHED (parse failed): {prod.get('name')} -> name={name}, size={size}, color={color}")
        
        order_product = OrderProduct(
            order_id=order_id,
            order_product_id=prod.get("order_product_id"),
            product_id=prod.get("product_id"),
            variant_id=prod.get("variant_id"),
            sku=prod.get("sku"),
            ean=ean,
            name=prod.get("name"),
            quantity=prod.get("quantity", 1),
            price_brutto=prod.get("price_brutto"),
            auction_id=prod.get("auction_id"),
            attributes=prod.get("attributes"),
            location=prod.get("location"),
            product_size_id=product_size_id,
        )
        db.add(order_product)
    
    # Dodaj domyslny status dla nowego zamowienia
    if is_new_order:
        add_order_status(db, order_id, "pobrano", notes="Nowe zamowienie")
    
    return order


# Mapowanie statusow na typy emaili
_STATUS_EMAIL_MAP = {
    "pobrano": "confirmation",
    "przekazano_kurierowi": "shipment",
    "w_drodze": "shipment",
    "dostarczono": "delivery",
    "zwrot": "correction",
}


def _dispatch_status_email(db, order_id: str, status: str):
    """Wyslij email do klienta odpowiedni dla danego statusu.

    Sprawdza czy email danego typu nie zostal juz wyslany (deduplikacja).
    Bledy wysylki sa logowane ale nie przerywaja flow.
    """
    email_type = _STATUS_EMAIL_MAP.get(status)
    if not email_type:
        return

    from .services.invoice_service import _was_email_sent, _mark_email_sent

    order = db.query(Order).filter(Order.order_id == order_id).first()
    if not order or not order.email:
        return

    if _was_email_sent(order, email_type):
        return

    try:
        from .services.email_service import (
            send_order_confirmation,
            send_shipment_notification,
            send_delivery_confirmation,
            send_invoice_correction,
        )

        sent = False
        if email_type == "confirmation":
            sent = send_order_confirmation(order)
        elif email_type == "shipment":
            sent = send_shipment_notification(order)
        elif email_type == "delivery":
            sent = send_delivery_confirmation(order)
        elif email_type == "correction":
            sent = send_invoice_correction(order)

        if sent:
            _mark_email_sent(db, order, email_type)
            logger.info(
                "Email '%s' wyslany dla zamowienia %s", email_type, order_id
            )
    except Exception as exc:
        logger.error(
            "Blad wysylki emaila '%s' dla zamowienia %s: %s",
            email_type, order_id, exc,
        )


def add_order_status(db, order_id: str, status: str, skip_if_same: bool = True, allow_backwards: bool = False, send_email: bool = True, **kwargs) -> Optional[OrderStatusLog]:
    """
    Add a status log entry for an order.
    
    Args:
        db: Database session
        order_id: ID zamówienia
        status: Nowy status
        skip_if_same: Jeśli True, nie dodaje statusu jeśli ostatni status jest taki sam (domyślnie True)
        allow_backwards: Jeśli True, pozwala na cofanie statusów (domyślnie False)
        send_email: Jeśli True, wysyła email do klienta przy zmianie statusu (domyślnie True)
        **kwargs: tracking_number, courier_code, notes
    
    Returns:
        OrderStatusLog lub None jeśli pominięto (duplikat lub cofnięcie)
    """
    # Sprawdź ostatni status
    last_status = db.query(OrderStatusLog).filter(
        OrderStatusLog.order_id == order_id
    ).order_by(desc(OrderStatusLog.timestamp)).first()
    
    # Sprawdź czy to duplikat (ten sam status)
    if skip_if_same and last_status and last_status.status == status:
        return None  # Status się nie zmienił, pomijamy
    
    # Sprawdź hierarchię statusów (nie pozwól na cofanie)
    if not allow_backwards and last_status:
        last_priority = STATUS_HIERARCHY.get(last_status.status, -1)
        new_priority = STATUS_HIERARCHY.get(status, -1)
        
        # Jeśli nowy status ma niższy priorytet (cofanie) i nie jest statusem problemowym (999)
        if new_priority != 999 and last_priority != -1 and new_priority < last_priority:
            # Cofnięcie statusu - logujemy i pomijamy
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(
                f"Pominięto cofnięcie statusu zamówienia {order_id}: "
                f"{last_status.status} (priorytet {last_priority}) → {status} (priorytet {new_priority})"
            )
            return None
    
    log = OrderStatusLog(
        order_id=order_id,
        status=status,
        tracking_number=kwargs.get("tracking_number"),
        courier_code=kwargs.get("courier_code"),
        notes=kwargs.get("notes"),
    )
    db.add(log)

    # Wyslij email do klienta przy zmianie statusu
    if send_email:
        _dispatch_status_email(db, order_id, status)

    return log



@bp.route("/orders/api/products/search")
@login_required
def api_product_search():
    """API wyszukiwania produktow do formularza recznego zamowienia."""
    q = request.args.get("q", "").strip()
    if len(q) < 2:
        return jsonify([])

    with get_session() as db:
        from .models import Product, ProductSize
        query = (
            db.query(ProductSize)
            .join(Product, Product.id == ProductSize.product_id)
            .filter(ProductSize.quantity > 0)
        )

        # Szukaj po barcode, nazwie, kolorze, serii
        like_q = f"%{q}%"
        query = query.filter(
            (ProductSize.barcode.ilike(like_q))
            | (Product._name.ilike(like_q))
            | (Product.color.ilike(like_q))
            | (Product.series.ilike(like_q))
            | (Product.category.ilike(like_q))
            | (Product.brand.ilike(like_q))
        )

        results = []
        for ps in query.limit(20).all():
            product = ps.product
            label = f"{product.name} | {product.color or '-'} | {ps.size} | EAN: {ps.barcode or '-'} | Stan: {ps.quantity}"
            results.append({
                "name": f"{product.name} - {product.color or ''} - {ps.size}".strip(" -"),
                "ean": ps.barcode or "",
                "size": ps.size,
                "stock": ps.quantity,
                "label": label,
            })

    return jsonify(results)


@bp.route("/orders/add", methods=["GET", "POST"])
@login_required
def add_order():
    """Dodaj zamowienie reczne (OLX, sklep, inne platformy)."""
    if request.method == "GET":
        return render_template("add_order.html")

    # POST - tworzenie zamowienia
    f = request.form
    order_id = f"manual_{int(time.time())}_{secrets.token_hex(4)}"
    now_ts = int(time.time())

    # Prowizja
    commission_type = f.get("commission_type", "percent")
    try:
        commission_value = float(f.get("commission_value") or 0)
    except (ValueError, TypeError):
        commission_value = 0.0

    # Zbierz produkty z formularza
    names = request.form.getlist("prod_name[]")
    eans = request.form.getlist("prod_ean[]")
    qtys = request.form.getlist("prod_qty[]")
    prices = request.form.getlist("prod_price[]")

    products = []
    for i, name in enumerate(names):
        if not name.strip():
            continue
        price = float(prices[i]) if i < len(prices) and prices[i] else 0
        # Oblicz prowizje per produkt
        if commission_type == "percent" and commission_value > 0:
            comm_fee = round(price * commission_value / 100, 2)
        elif commission_type == "amount" and commission_value > 0:
            comm_fee = commission_value
        else:
            comm_fee = 0.0

        products.append({
            "name": name.strip(),
            "ean": eans[i].strip() if i < len(eans) else "",
            "quantity": int(qtys[i]) if i < len(qtys) and qtys[i] else 1,
            "price_brutto": price,
            "commission_fee": comm_fee,
        })

    if not products:
        flash("Dodaj co najmniej jeden produkt.", "danger")
        return render_template("add_order.html")

    order_data = {
        "order_id": order_id,
        "external_order_id": f.get("external_order_id", "").strip() or None,
        "platform": f.get("platform", "olx"),
        "customer": f.get("customer_name", "").strip(),
        "delivery_fullname": f.get("delivery_fullname", "").strip() or f.get("customer_name", "").strip(),
        "email": f.get("email", "").strip() or None,
        "phone": f.get("phone", "").strip() or None,
        "delivery_company": f.get("delivery_company", "").strip() or None,
        "delivery_address": f.get("delivery_address", "").strip(),
        "delivery_postcode": f.get("delivery_postcode", "").strip() or None,
        "delivery_city": f.get("delivery_city", "").strip(),
        "delivery_country": "Polska",
        "delivery_country_code": "PL",
        "delivery_method": f.get("delivery_method", ""),
        "delivery_price": float(f.get("delivery_price") or 0),
        "delivery_package_nr": f.get("delivery_package_nr", "").strip() or None,
        "delivery_point_id": f.get("delivery_point_id", "").strip() or None,
        "delivery_point_address": f.get("delivery_point_address", "").strip() or None,
        "delivery_point_city": f.get("delivery_point_city", "").strip() or None,
        "payment_method": f.get("payment_method", "przelew"),
        "payment_method_cod": "1" if f.get("payment_method") == "za_pobraniem" else "0",
        "payment_done": float(f.get("payment_done") or 0),
        "want_invoice": "1" if f.get("want_invoice") else "0",
        "invoice_fullname": f.get("invoice_fullname", "").strip() or None,
        "invoice_company": f.get("invoice_company", "").strip() or None,
        "invoice_nip": f.get("invoice_nip", "").strip() or None,
        "invoice_address": f.get("invoice_address", "").strip() or None,
        "invoice_postcode": f.get("invoice_postcode", "").strip() or None,
        "invoice_city": f.get("invoice_city", "").strip() or None,
        "invoice_country": "Polska",
        "user_comments": f.get("user_comments", "").strip() or None,
        "admin_comments": f.get("admin_comments", "").strip() or None,
        "currency": "PLN",
        "confirmed": True,
        "date_add": now_ts,
        "date_confirmed": now_ts,
        "products": products,
    }

    with get_session() as db:
        order = sync_order_from_data(db, order_data)
        add_order_status(db, order.order_id, "pobrano",
                         notes=f"Zamowienie reczne ({order_data['platform']})")
        db.commit()
        flash(f"Zamowienie {order.order_id} zostalo utworzone.", "success")
        return redirect(url_for("orders.order_detail", order_id=order.order_id))


@bp.route("/orders/sync-all", methods=["POST"])
@login_required
def sync_all_orders():
    """Reczne uruchomienie syncu zamowien z Allegro Events API."""
    try:
        from .order_sync_scheduler import _sync_from_allegro_events
        from flask import current_app as app

        current_app.logger.info("Reczny sync zamowien z Allegro Events API")
        ev_stats = _sync_from_allegro_events(app._get_current_object())
        
        synced = ev_stats.get("orders_synced", 0)
        cancelled = ev_stats.get("orders_cancelled", 0)
        current_app.logger.info(
            "Reczny sync zakonczony: %d zsynchronizowanych, %d anulowanych",
            synced, cancelled,
        )
        flash(
            f"Zsynchronizowano {synced} zamowien z Allegro (anulowane: {cancelled})",
            "success",
        )
    except Exception as exc:
        current_app.logger.error("Blad recznego syncu zamowien: %s", exc)
        flash(f"Blad synchronizacji: {exc}", "error")
    
    return redirect(url_for(".orders_list"))


@bp.route("/orders/sync-allegro", methods=["POST"])
@login_required
def sync_allegro_orders():
    """
    Synchronizacja zamowien bezposrednio z Allegro REST API.
    
    Allegro zwraca zamowienia z ostatnich 12 miesiecy (max).
    Paginacja: offset/limit, max offset+limit = 10000.
    Uzywa GET /order/checkout-forms.
    """
    try:
        from .allegro_api.orders import (
            fetch_all_allegro_orders,
            parse_allegro_order_to_data,
            get_allegro_internal_status,
        )

        current_app.logger.info("Rozpoczynam sync zamowien z Allegro API...")

        # Pobierz wszystkie zamowienia z Allegro
        checkout_forms = fetch_all_allegro_orders()

        synced = 0
        updated = 0
        skipped = 0

        with get_session() as db:
            for cf in checkout_forms:
                try:
                    order_data = parse_allegro_order_to_data(cf)
                    cf_id = cf.get("id", "")

                    # Sprawdz czy zamowienie juz istnieje (po external_order_id lub order_id)
                    existing = db.query(Order).filter(
                        or_(
                            Order.external_order_id == cf_id,
                            Order.order_id == f"allegro_{cf_id}",
                        )
                    ).first()

                    if existing:
                        # Zamowienie juz istnieje - zaktualizuj brakujace pola
                        if not existing.user_login and order_data.get("user_login"):
                            existing.user_login = order_data["user_login"]
                        if not existing.email and order_data.get("email"):
                            existing.email = order_data["email"]
                        if not existing.phone and order_data.get("phone"):
                            existing.phone = order_data["phone"]
                        if not existing.external_order_id:
                            existing.external_order_id = cf_id

                        # Zaktualizuj status na podstawie fulfillment z Allegro
                        internal_status = get_allegro_internal_status(order_data)
                        allegro_status = order_data.get("_allegro_status", "")
                        fulfillment = order_data.get("_allegro_fulfillment_status", "")
                        added = add_order_status(
                            db,
                            existing.order_id,
                            internal_status,
                            notes=f"Aktualizacja z Allegro API (status: {allegro_status}, fulfillment: {fulfillment})",
                        )
                        if added:
                            current_app.logger.info(
                                "Zaktualizowano status %s -> %s (fulfillment: %s)",
                                existing.order_id[:30], internal_status, fulfillment,
                            )
                        updated += 1
                    else:
                        # Nowe zamowienie - dodaj
                        sync_order_from_data(db, order_data)

                        # Ustaw status na podstawie danych Allegro
                        internal_status = get_allegro_internal_status(order_data)
                        allegro_status = order_data.get("_allegro_status", "")
                        fulfillment = order_data.get("_allegro_fulfillment_status", "")
                        add_order_status(
                            db,
                            order_data["order_id"],
                            internal_status,
                            notes=f"Zsynchronizowano z Allegro API (status: {allegro_status}, fulfillment: {fulfillment})",
                        )
                        synced += 1

                except Exception as exc:
                    current_app.logger.warning(
                        "Blad przetwarzania zamowienia Allegro %s: %s",
                        cf.get("id", "?"), exc
                    )
                    skipped += 1

            db.commit()

        msg = (
            f"Allegro API: {synced} nowych, {updated} zaktualizowanych, "
            f"{skipped} pominieto (laczne: {len(checkout_forms)} z API)"
        )
        current_app.logger.info(msg)
        flash(msg, "success")

    except Exception as exc:
        current_app.logger.error("Blad sync zamowien z Allegro API: %s", exc)
        flash(f"Blad synchronizacji z Allegro: {exc}", "error")

    return redirect(url_for(".orders_list"))


# Synchronizacja statusów przesyłek jest automatyczna (co godzinę w schedulerze)
# Nie potrzebujemy ręcznej synchronizacji ani osobnego widoku śledzenia
# Historia wysyłki jest zintegrowana w order_detail.html
