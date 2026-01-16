"""Orders blueprint - view and manage BaseLinker orders."""
import json
import time
import logging
from datetime import datetime, timedelta
from typing import Optional
from decimal import Decimal

from flask import Blueprint, render_template, abort, request, flash, redirect, url_for, current_app, after_this_request, send_file
from sqlalchemy import desc, or_

from .auth import login_required
from .db import get_session
from .models import Order, OrderProduct, OrderStatusLog, ProductSize, Product, PurchaseBatch, Return, ReturnStatusLog, AllegroOffer
from .settings_store import settings_store

logger = logging.getLogger(__name__)

bp = Blueprint("orders", __name__)


# All valid statuses for the system
# Flow: pobrano → wydrukowano → spakowano → przekazano_kurierowi → w_drodze → w_punkcie → gotowe_do_odbioru → dostarczono → zakończono
VALID_STATUSES = [
    # Etap wewnętrzny (magazyn)
    "pobrano",              # Pobrano z BaseLinker
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

# Status IDs - ALL statuses for complete archive
ALL_STATUS_IDS = [
    91615,  # Nowe zamówienie
    91616,  # Oczekujące
    91617,  # W realizacji
    91618,  # Gotowe do wysyłki
    91619,  # Wysłane
    91620,  # W transporcie
    91621,  # Zakończone
    91622,  # Anulowane
    91623,  # Zwrot
]

# Active status IDs - only non-completed orders for regular sync
ACTIVE_STATUS_IDS = [
    91615,  # Nowe zamówienie
    91616,  # Oczekujące
    91617,  # W realizacji
    91618,  # Gotowe do wysyłki
    91619,  # Wysłane
    91620,  # W transporcie
    # Excluded: 91621 (Zakończone), 91622 (Anulowane), 91623 (Zwrot)
]

# Etapy wysyłki dla timeline - kolejność ma znaczenie!
# Format: (status_key, ikona, etykieta)
SHIPPING_STAGES = [
    ("pobrano", "bi-inbox", "Pobrano"),
    ("wydrukowano", "bi-printer", "Wydrukowano"),
    ("spakowano", "bi-box-seam", "Spakowano"),
    ("przekazano_kurierowi", "bi-person-badge", "Przekazano"),
    ("w_drodze", "bi-truck", "W drodze"),
    ("gotowe_do_odbioru", "bi-geo-alt", "Do odbioru"),
    ("dostarczono", "bi-check-circle", "Dostarczono"),
]

# Etapy zwrotu dla timeline
# Format: (status_key, ikona, etykieta)
RETURN_STAGES = [
    ("pending", "bi-flag", "Zgloszono"),
    ("in_transit", "bi-truck", "W drodze"),
    ("delivered", "bi-box-arrow-in-down", "Odebrano"),
    ("completed", "bi-check-circle", "Zakonczono"),
]
# Map BaseLinker status_id to our internal status
BASELINKER_STATUS_MAP = {
    91615: "pobrano",           # Nowe zamówienie
    91616: "niewydrukowano",    # Oczekujące
    91617: "wydrukowano",       # W realizacji
    91618: "wydrukowano",       # Gotowe do wysyłki - NIE ustawiamy "spakowano" automatycznie, tylko przez skanowanie
    91619: "w_drodze",          # Wysłane
    91620: "w_drodze",          # W transporcie
    91621: "dostarczono",       # Zakończone
    91622: "anulowano",         # Anulowane
    91623: "zwrot",             # Zwrot
}


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


def _calculate_allegro_smart_cost(order_value: Decimal, delivery_method: str) -> Optional[Decimal]:
    """Calculate Allegro Smart shipping cost based on order value and delivery method.
    
    Uses Allegro Smart pricing tiers from:
    https://help.allegro.com/pl/sell/a/allegro-smart-na-allegro-pl-informacje-dla-sprzedajacych-9g0rWRXKxHG
    """
    # Define pricing tiers based on order value
    if order_value < 30:
        return None  # Not eligible for Smart
    elif 30 <= order_value < 45:
        tier = "30-45"
    elif 45 <= order_value < 65:
        tier = "45-65"
    elif 65 <= order_value < 100:
        tier = "65-100"
    elif 100 <= order_value < 150:
        tier = "100-150"
    else:  # >= 150
        tier = "150+"
    
    # Normalize delivery method name
    method_lower = delivery_method.lower() if delivery_method else ""
    
    # Define costs for each method and tier
    # Format: {method_key: {tier: cost}}
    COSTS = {
        # Paczkomaty InPost (non-Delivery)
        "paczkomaty inpost": {
            "30-45": Decimal("1.59"),
            "45-65": Decimal("3.09"),
            "65-100": Decimal("4.99"),
            "100-150": Decimal("7.59"),
            "150+": Decimal("9.99"),
        },
        # Allegro Delivery methods (lower costs)
        "allegro delivery": {
            "30-45": Decimal("0.99"),
            "45-65": Decimal("1.89"),
            "65-100": Decimal("3.59"),
            "100-150": Decimal("5.89"),
            "150+": Decimal("7.79"),
        },
        # Kurier DPD (non-Delivery)
        "kurier dpd": {
            "30-45": Decimal("1.99"),
            "45-65": Decimal("3.99"),
            "65-100": Decimal("5.79"),
            "100-150": Decimal("9.09"),
            "150+": Decimal("11.49"),
        },
        # Kurier Allegro Delivery
        "kurier delivery": {
            "30-45": Decimal("1.79"),
            "45-65": Decimal("3.69"),
            "65-100": Decimal("5.39"),
            "100-150": Decimal("8.59"),
            "150+": Decimal("10.89"),
        },
        # Pocztex
        "pocztex": {
            "30-45": Decimal("1.29"),
            "45-65": Decimal("2.49"),
            "65-100": Decimal("4.29"),
            "100-150": Decimal("6.69"),
            "150+": Decimal("8.89"),
        },
        # Przesyłka polecona
        "przesyłka polecona": {
            "30-45": Decimal("0.79"),
            "45-65": Decimal("1.49"),
            "65-100": Decimal("2.29"),
            "100-150": Decimal("3.49"),
            "150+": Decimal("4.29"),
        },
        # MiniPrzesyłka
        "miniprzesyłka": {
            "30-45": Decimal("0.79"),
            "45-65": Decimal("1.49"),
            "65-100": Decimal("2.29"),
            "100-150": Decimal("3.49"),
            "150+": Decimal("4.29"),
        },
    }
    
    # Match delivery method to cost table
    if "paczkomat" in method_lower or "inpost" in method_lower:
        if "delivery" not in method_lower:
            return COSTS["paczkomaty inpost"].get(tier)
        else:
            return COSTS["allegro delivery"].get(tier)
    elif "kurier" in method_lower:
        if "delivery" in method_lower or "dhl" in method_lower or "orlen" in method_lower or "one" in method_lower:
            return COSTS["kurier delivery"].get(tier)
        else:
            return COSTS["kurier dpd"].get(tier)
    elif "pocztex" in method_lower:
        return COSTS["pocztex"].get(tier)
    elif "polecona" in method_lower:
        return COSTS["przesyłka polecona"].get(tier)
    elif "mini" in method_lower:
        return COSTS["miniprzesyłka"].get(tier)
    elif "automat" in method_lower or "punkt" in method_lower or "box" in method_lower:
        # All automats and pickup points use Allegro Delivery pricing
        return COSTS["allegro delivery"].get(tier)
    
    # If method not recognized, return None
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
    
    # Limit per_page to reasonable values
    if per_page not in [10, 25, 50, 100]:
        per_page = 10
    
    with get_session() as db:
        query = db.query(Order)
        
        # Apply search filter
        if search:
            search_pattern = f"%{search}%"
            query = query.filter(
                or_(
                    Order.order_id.ilike(search_pattern),
                    Order.external_order_id.ilike(search_pattern),
                    Order.customer_name.ilike(search_pattern),
                    Order.email.ilike(search_pattern),
                    Order.phone.ilike(search_pattern),
                )
            )
        
        # Apply sorting
        if sort_by == "order_id":
            sort_col = Order.order_id
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
        )


@bp.route("/order/<order_id>")
@login_required
def order_detail(order_id: str):
    """Display detailed view of a single order."""
    with get_session() as db:
        order = db.query(Order).filter(Order.order_id == order_id).first()
        if not order:
            abort(404)
        
        # Get order products with warehouse links
        products = []
        for op in order.products:
            # Try to link to warehouse via EAN or auction_id->AllegroOffer
            warehouse_product = None
            ps = None
            
            # 1. Najpierw probuj po EAN
            if op.ean:
                ps = db.query(ProductSize).filter(ProductSize.barcode == op.ean).first()
            
            # 2. Jesli nie znaleziono, probuj przez auction_id -> AllegroOffer
            if not ps and op.auction_id:
                allegro_offer = db.query(AllegroOffer).filter(
                    AllegroOffer.offer_id == op.auction_id
                ).first()
                if allegro_offer and allegro_offer.product_size_id:
                    ps = db.query(ProductSize).filter(
                        ProductSize.id == allegro_offer.product_size_id
                    ).first()
            
            if ps:
                warehouse_product = {
                    "id": ps.product_id,
                    "product_size_id": ps.id,
                    "name": ps.product.name if ps.product else None,
                    "color": ps.product.color if ps.product else None,
                    "size": ps.size,
                    "quantity_in_stock": ps.quantity,
                }
            
            products.append({
                "id": op.id,
                "name": op.name,
                "sku": op.sku,
                "ean": op.ean,
                "quantity": op.quantity,
                "price_brutto": op.price_brutto,
                "attributes": op.attributes,
                "auction_id": op.auction_id,
                "warehouse_product": warehouse_product,
            })
        
        # Calculate Allegro Smart shipping cost (fallback if Billing API fails)
        shipping_cost = None
        if order.payment_done and order.delivery_method:
            shipping_cost = _calculate_allegro_smart_cost(
                Decimal(str(order.payment_done)),
                order.delivery_method
            )
        
        # Calculate financial metrics - try to get real data from Allegro Billing API
        sale_price = Decimal(str(order.payment_done)) if order.payment_done else Decimal("0")
        
        # Domyslne wartosci (fallback jesli API nie zwroci danych)
        allegro_commission = Decimal("0")
        listing_fee = Decimal("0")
        allegro_shipping_fee = Decimal("0")
        promo_fee = Decimal("0")
        other_fees = Decimal("0")
        billing_data_available = False
        billing_entries = []
        
        # Probuj pobrac rzeczywiste dane z Billing API
        try:
            access_token = settings_store.get("ALLEGRO_ACCESS_TOKEN")
            # Uzywamy external_order_id (UUID Allegro) zamiast order_id (BaseLinker)
            allegro_order_id = order.external_order_id
            if access_token and allegro_order_id:
                from .allegro_api import get_order_billing_summary
                billing_summary = get_order_billing_summary(access_token, allegro_order_id)
                
                if billing_summary.get("success"):
                    allegro_commission = billing_summary["commission"]
                    listing_fee = billing_summary["listing_fee"]
                    allegro_shipping_fee = billing_summary["shipping_fee"]
                    promo_fee = billing_summary["promo_fee"]
                    other_fees = billing_summary["other_fees"]
                    billing_entries = billing_summary["entries"]
                    billing_data_available = True
                    logger.info(f"Pobrano dane billingowe dla zamowienia {order.order_id} "
                               f"(Allegro: {allegro_order_id}): prowizja={allegro_commission}, "
                               f"wystawienie={listing_fee}, wysylka={allegro_shipping_fee}, promo={promo_fee}")
                else:
                    logger.warning(f"Nie udalo sie pobrac danych billingowych dla {order.order_id} "
                                  f"(Allegro: {allegro_order_id}): {billing_summary.get('error')}")
        except Exception as e:
            logger.warning(f"Blad podczas pobierania danych billingowych dla {order.order_id} "
                          f"(Allegro: {allegro_order_id if 'allegro_order_id' in dir() else 'N/A'}): {e}")
        
        # Jesli nie udalo sie pobrac z API, uzyj szacunkow
        if not billing_data_available:
            allegro_commission = sale_price * Decimal("0.123")  # 12.3% szacunkowo
            listing_fee = Decimal("0")
            allegro_shipping_fee = Decimal("0")
            promo_fee = Decimal("0")
            other_fees = Decimal("0")
        
        # Suma wszystkich oplat Allegro
        total_allegro_fees = allegro_commission + listing_fee + allegro_shipping_fee + promo_fee + other_fees
        
        # Calculate purchase cost from order products
        purchase_cost = Decimal("0")
        for op in order.products:
            if op.product_size and op.product_size.product:
                # Get latest purchase batch for this product
                latest_batch = (
                    db.query(PurchaseBatch)
                    .filter(
                        PurchaseBatch.product_id == op.product_size.product_id,
                        PurchaseBatch.size == op.product_size.size
                    )
                    .order_by(desc(PurchaseBatch.purchase_date))
                    .first()
                )
                if latest_batch:
                    purchase_cost += Decimal(str(latest_batch.price)) * op.quantity
        
        # Calculate real profit (using real Allegro fees if available, otherwise shipping_cost estimate)
        # Jesli mamy dane z Billing API, uzywamy ich w calosci
        # Jesli nie, uzywamy szacunkowej prowizji + shipping_cost
        if billing_data_available:
            real_profit = sale_price - total_allegro_fees - purchase_cost
        else:
            real_profit = sale_price - allegro_commission - (shipping_cost or Decimal("0")) - purchase_cost
        
        # Generate tracking URL
        tracking_url = _get_tracking_url(order.courier_code, order.delivery_package_module, order.delivery_package_nr, order.delivery_method)
        
        # Get status history
        status_logs = (
            db.query(OrderStatusLog)
            .filter(OrderStatusLog.order_id == order_id)
            .order_by(desc(OrderStatusLog.timestamp))
            .all()
        )
        
        # Build status history with deduplication (keep only newest occurrence of each status)
        status_history = []
        seen_statuses = set()
        for log in status_logs:
            # Skip if we already have this status (keeps first/newest occurrence)
            if log.status in seen_statuses:
                continue
            seen_statuses.add(log.status)
            
            status_text, status_class = _get_status_display(log.status)
            status_history.append({
                "status": log.status,
                "status_text": status_text,
                "status_class": status_class,
                "timestamp": log.timestamp,
                "tracking_number": log.tracking_number,
                "courier_code": log.courier_code,
                "notes": log.notes,
            })
        
        # Get current status
        current_status = status_history[0] if status_history else {
            "status": "niewydrukowano",
            "status_text": "Niewydrukowano",
            "status_class": "bg-secondary",
        }
        
        # Przygotuj dane do timeline
        # Określ aktualny etap na podstawie najnowszego statusu
        current_stage_key = current_status.get("status", "pobrano")
        # Znajdź indeks aktualnego etapu
        stage_keys = [s[0] for s in SHIPPING_STAGES]
        current_stage_index = -1
        if current_stage_key in stage_keys:
            current_stage_index = stage_keys.index(current_stage_key)
        
        # Pobierz informacje o zwrocie (jesli istnieje)
        return_info = None
        return_status_history = []
        return_stage_index = -1
        
        active_return = db.query(Return).filter(
            Return.order_id == order_id,
            Return.status != "cancelled"  # Nie pokazuj anulowanych
        ).order_by(desc(Return.created_at)).first()
        
        if active_return:
            # Mapowanie statusow zwrotu na wyswietlanie
            RETURN_STATUS_MAP = {
                "pending": ("Zgloszono zwrot", "bg-warning text-dark"),
                "in_transit": ("Paczka zwrotna w drodze", "bg-info"),
                "delivered": ("Paczka zwrotna odebrana", "bg-primary"),
                "completed": ("Zwrot zakonczony", "bg-success"),
                "cancelled": ("Zwrot anulowany", "bg-secondary"),
            }
            
            status_text, status_class = RETURN_STATUS_MAP.get(
                active_return.status, 
                (active_return.status, "bg-secondary")
            )
            
            # Parsuj items_json
            import json as json_module
            return_items = []
            if active_return.items_json:
                try:
                    return_items = json_module.loads(active_return.items_json)
                except (json_module.JSONDecodeError, TypeError):
                    pass
            
            return_info = {
                "id": active_return.id,
                "status": active_return.status,
                "status_text": status_text,
                "status_class": status_class,
                "customer_name": active_return.customer_name,
                "return_items": return_items,
                "return_tracking_number": active_return.return_tracking_number,
                "return_carrier": active_return.return_carrier,
                "messenger_notified": active_return.messenger_notified,
                "stock_restored": active_return.stock_restored,
                "notes": active_return.notes,
                "created_at": active_return.created_at,
                "updated_at": active_return.updated_at,
            }
            
            # Historia statusow zwrotu
            return_logs = db.query(ReturnStatusLog).filter(
                ReturnStatusLog.return_id == active_return.id
            ).order_by(desc(ReturnStatusLog.timestamp)).all()
            
            for log in return_logs:
                log_status_text, log_status_class = RETURN_STATUS_MAP.get(
                    log.status, (log.status, "bg-secondary")
                )
                return_status_history.append({
                    "status": log.status,
                    "status_text": log_status_text,
                    "status_class": log_status_class,
                    "timestamp": log.timestamp,
                    "notes": log.notes,
                })
            
            # Indeks etapu zwrotu dla timeline
            return_stage_keys = [s[0] for s in RETURN_STAGES]
            if active_return.status in return_stage_keys:
                return_stage_index = return_stage_keys.index(active_return.status)
        
        rendered = render_template(
            "order_detail.html",
            order=order,
            products=products,
            status_history=status_history,
            current_status=current_status,
            date_add=_unix_to_datetime(order.date_add),
            date_confirmed=_unix_to_datetime(order.date_confirmed),
            shipping_cost=shipping_cost,
            allegro_commission=allegro_commission,
            listing_fee=listing_fee,
            allegro_shipping_fee=allegro_shipping_fee,
            promo_fee=promo_fee,
            other_fees=other_fees,
            total_allegro_fees=total_allegro_fees,
            billing_data_available=billing_data_available,
            billing_entries=billing_entries,
            purchase_cost=purchase_cost,
            real_profit=real_profit,
            tracking_url=tracking_url,
            shipping_stages=SHIPPING_STAGES,
            current_stage_index=current_stage_index,
            # Dane zwrotu
            return_info=return_info,
            return_status_history=return_status_history,
            return_stages=RETURN_STAGES,
            return_stage_index=return_stage_index,
        )
        
        # Zapobiegaj cache przegladarki
        response = current_app.make_response(rendered)
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        return response


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
            pid = pkg.get("package_id")
            code = pkg.get("courier_code")
            if not pid or not code:
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
            pid = pkg.get("package_id")
            code = pkg.get("courier_code")
            if not pid or not code:
                continue
            label_data, ext = print_agent.get_label(code, pid)
            if label_data:
                # Save to temporary file and send
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext}")
                tmp.write(label_data)
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
    Create or update Order from BaseLinker data (last_order_data format).
    Called from print_agent when processing orders.
    """
    order_id = str(order_data.get("order_id"))
    
    # Check if order exists
    order = db.query(Order).filter(Order.order_id == order_id).first()
    is_new_order = False
    if not order:
        order = Order(order_id=order_id)
        db.add(order)
        is_new_order = True
    
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
    order.payment_method_cod = order_data.get("payment_method_cod") == "1"
    order.payment_done = order_data.get("payment_done")
    order.user_comments = order_data.get("user_comments")
    order.admin_comments = order_data.get("admin_comments")
    order.courier_code = order_data.get("courier_code")
    order.delivery_package_module = order_data.get("delivery_package_module")
    order.delivery_package_nr = order_data.get("delivery_package_nr")
    
    # Store raw products JSON
    products_list = order_data.get("products", [])
    order.products_json = json.dumps(products_list) if products_list else None
    
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
            
            if name and size and color:
                # Match by series/color/size
                ps = (
                    db.query(ProductSize)
                    .join(Product)
                    .filter(
                        Product.series.ilike(f"%{name}%"),
                        Product.color.ilike(f"%{color}%"),
                        ProductSize.size == size
                    )
                    .first()
                )
                if ps:
                    product_size_id = ps.id
                    current_app.logger.info(f"✅ Matched: {prod.get('name')} -> {name}/{color}/{size} -> product_size_id={ps.id}")
                else:
                    current_app.logger.warning(f"❌ NOT MATCHED: {prod.get('name')} -> parsed: {name}/{color}/{size}")
            else:
                current_app.logger.warning(f"❌ NOT MATCHED (parse failed): {prod.get('name')} -> name={name}, size={size}, color={color}")
        
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
    
    # Check and update status based on BaseLinker status_id
    bl_status_id = order_data.get("order_status_id")
    internal_status = BASELINKER_STATUS_MAP.get(bl_status_id, "pobrano")
    
    # Get current status from log
    current_status_log = db.query(OrderStatusLog).filter(
        OrderStatusLog.order_id == order_id
    ).order_by(desc(OrderStatusLog.timestamp)).first()
    
    current_status = current_status_log.status if current_status_log else None
    
    # Add or update status if changed or new order
    if is_new_order or current_status != internal_status:
        status_note = {
            "w_drodze": "Zsynchronizowano ze statusu Wysłane/W transporcie",
            "dostarczono": "Zsynchronizowano ze statusu Zakończone",
        }.get(internal_status, f"Zaktualizowano z BaseLinker (status_id: {bl_status_id})")
        add_order_status(db, order_id, internal_status, notes=status_note)
    
    return order


def add_order_status(db, order_id: str, status: str, skip_if_same: bool = True, allow_backwards: bool = False, **kwargs) -> Optional[OrderStatusLog]:
    """
    Add a status log entry for an order.
    
    Args:
        db: Database session
        order_id: ID zamówienia
        status: Nowy status
        skip_if_same: Jeśli True, nie dodaje statusu jeśli ostatni status jest taki sam (domyślnie True)
        allow_backwards: Jeśli True, pozwala na cofanie statusów (domyślnie False)
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
    return log


def _sync_orders_from_baselinker(status_ids: list[int], days: int = None) -> int:
    """
    Sync orders from BaseLinker for given status IDs.
    If days is None, fetches ALL orders from archives (no date limit).
    Returns number of orders synced.
    """
    from .config import settings
    import requests
    
    synced = 0
    
    api_url = "https://api.baselinker.com/connector.php"
    headers = {"X-BLToken": settings.API_TOKEN}
    
    for status_id in status_ids:
        try:
            # Build parameters - omit date_from for full archive sync
            params_dict = {
                "status_id": status_id,
                "include_products": 1,
            }
            
            # Only add date_from if days is specified
            if days is not None:
                date_from = int(time.time()) - (days * 24 * 60 * 60)
                params_dict["date_from"] = date_from
            
            params = {
                "method": "getOrders",
                "parameters": json.dumps(params_dict)
            }
            response = requests.post(api_url, headers=headers, data=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            if data.get("status") != "SUCCESS":
                current_app.logger.warning(
                    "BaseLinker API error for status %s: %s",
                    status_id, data.get("error_message", "Unknown error")
                )
                continue
                
            orders = data.get("orders", [])
            
            with get_session() as db:
                for order in orders:
                    order_data = {
                        "order_id": order.get("order_id"),
                        "external_order_id": order.get("external_order_id"),
                        "shop_order_id": order.get("shop_order_id"),
                        "customer": order.get("delivery_fullname"),
                        "email": order.get("email"),
                        "phone": order.get("phone"),
                        "user_login": order.get("user_login"),
                        "platform": order.get("order_source"),
                        "order_source_id": order.get("order_source_id"),
                        "order_status_id": order.get("order_status_id"),
                        "confirmed": order.get("confirmed", False),
                        "date_add": order.get("date_add"),
                        "date_confirmed": order.get("date_confirmed"),
                        "date_in_status": order.get("date_in_status"),
                        "shipping": order.get("delivery_method"),
                        "delivery_method_id": order.get("delivery_method_id"),
                        "delivery_price": order.get("delivery_price"),
                        "delivery_fullname": order.get("delivery_fullname"),
                        "delivery_company": order.get("delivery_company"),
                        "delivery_address": order.get("delivery_address"),
                        "delivery_city": order.get("delivery_city"),
                        "delivery_postcode": order.get("delivery_postcode"),
                        "delivery_country": order.get("delivery_country"),
                        "delivery_country_code": order.get("delivery_country_code"),
                        "delivery_point_id": order.get("delivery_point_id"),
                        "delivery_point_name": order.get("delivery_point_name"),
                        "delivery_point_address": order.get("delivery_point_address"),
                        "delivery_point_postcode": order.get("delivery_point_postcode"),
                        "delivery_point_city": order.get("delivery_point_city"),
                        "invoice_fullname": order.get("invoice_fullname"),
                        "invoice_company": order.get("invoice_company"),
                        "invoice_nip": order.get("invoice_nip"),
                        "invoice_address": order.get("invoice_address"),
                        "invoice_city": order.get("invoice_city"),
                        "invoice_postcode": order.get("invoice_postcode"),
                        "invoice_country": order.get("invoice_country"),
                        "want_invoice": order.get("want_invoice"),
                        "currency": order.get("currency", "PLN"),
                        "payment_method": order.get("payment_method"),
                        "payment_method_cod": order.get("payment_method_cod"),
                        "payment_done": order.get("payment_done"),
                        "user_comments": order.get("user_comments"),
                        "admin_comments": order.get("admin_comments"),
                        "delivery_package_module": order.get("delivery_package_module"),
                        "delivery_package_nr": order.get("delivery_package_nr"),
                        "products": order.get("products", []),
                    }
                    sync_order_from_data(db, order_data)
                    synced += 1
                db.commit()
                
        except Exception as exc:
            current_app.logger.error(
                "Error syncing orders from status %s: %s", status_id, exc
            )
    
    return synced


# Synchronizacja statusów przesyłek jest automatyczna (co godzinę w schedulerze)
# Nie potrzebujemy ręcznej synchronizacji ani osobnego widoku śledzenia
# Historia wysyłki jest zintegrowana w order_detail.html
