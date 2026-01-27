"""
OrderDetailBuilder - serwis budujacy szczegoly zamowienia.

Wyodrebniony z orders.py dla lepszej czytelnosci i testowalnosci.
"""
import json
import logging
from decimal import Decimal
from typing import Optional

from sqlalchemy import desc

from ..db import get_session
from ..models import (
    Order, 
    OrderProduct, 
    OrderStatusLog,
    ProductSize, 
    AllegroOffer,
    PurchaseBatch,
    Return,
    ReturnStatusLog,
)
from ..settings_store import settings_store


logger = logging.getLogger(__name__)


# Statusy wysylki z ikonami i opisami
SHIPPING_STAGES = [
    ("pobrano", "Pobrano do magazynu", "download", "Zamowienie pobrane z Allegro"),
    ("niewydrukowano", "Niewydrukowano", "file-text", "Etykieta do wydruku"),
    ("wydrukowano", "Wydrukowano", "printer", "Etykieta wydrukowana"),
    ("wwyslane", "W transporcie", "truck", "Paczka nadana"),
    ("dostarczone", "Dostarczone", "package", "Paczka dostarczona"),
]

# Statusy zwrotu z ikonami
RETURN_STAGES = [
    ("pending", "Zgloszono", "alert-circle", "Klient zglosil zwrot"),
    ("in_transit", "W drodze", "truck", "Paczka zwrotna w transporcie"),
    ("delivered", "Odebrano", "package", "Paczka zwrotna odebrana"),
    ("completed", "Zakonczono", "check-circle", "Zwrot rozliczony"),
]

# Mapowanie statusow na wyswietlanie
STATUS_DISPLAY_MAP = {
    "pobrano": ("Pobrano do magazynu", "bg-info"),
    "niewydrukowano": ("Niewydrukowano", "bg-secondary"),
    "wydrukowano": ("Wydrukowano", "bg-primary"),
    "wwyslane": ("W transporcie", "bg-warning text-dark"),
    "dostarczone": ("Dostarczone", "bg-success"),
    "zwrot": ("Zwrot", "bg-danger"),
}

RETURN_STATUS_MAP = {
    "pending": ("Zgloszono zwrot", "bg-warning text-dark"),
    "in_transit": ("Paczka zwrotna w drodze", "bg-info"),
    "delivered": ("Paczka zwrotna odebrana", "bg-primary"),
    "completed": ("Zwrot zakonczony", "bg-success"),
    "cancelled": ("Zwrot anulowany", "bg-secondary"),
}


class OrderDetailBuilder:
    """Serwis budujacy szczegoly zamowienia."""
    
    def __init__(self, db_session):
        self.db = db_session
    
    def build_products_list(self, order: Order) -> list[dict]:
        """Buduj liste produktow z powiazaniami do magazynu."""
        products = []
        for op in order.products:
            warehouse_product = None
            ps = None
            
            # 1. Najpierw probuj po EAN
            if op.ean:
                ps = self.db.query(ProductSize).filter(ProductSize.barcode == op.ean).first()
            
            # 2. Jesli nie znaleziono, probuj przez auction_id -> AllegroOffer
            if not ps and op.auction_id:
                allegro_offer = self.db.query(AllegroOffer).filter(
                    AllegroOffer.offer_id == op.auction_id
                ).first()
                if allegro_offer and allegro_offer.product_size_id:
                    ps = self.db.query(ProductSize).filter(
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
        
        return products
    
    def fetch_billing_data(
        self, 
        order: Order, 
        sale_price: Decimal
    ) -> dict:
        """
        Pobierz dane billingowe z Allegro API.
        
        Returns:
            dict z kluczami: commission, listing_fee, shipping_fee, promo_fee,
            other_fees, billing_data_available, billing_entries, fee_details,
            estimated_shipping
        """
        result = {
            "commission": Decimal("0"),
            "listing_fee": Decimal("0"),
            "shipping_fee": Decimal("0"),
            "promo_fee": Decimal("0"),
            "other_fees": Decimal("0"),
            "billing_data_available": False,
            "billing_entries": [],
            "fee_details": [],
            "estimated_shipping": None,
        }
        
        try:
            access_token = settings_store.get("ALLEGRO_ACCESS_TOKEN")
            allegro_order_id = order.external_order_id
            
            if access_token and allegro_order_id:
                from ..allegro_api import get_order_billing_summary
                
                billing_summary = get_order_billing_summary(
                    access_token, 
                    allegro_order_id,
                    delivery_method=order.delivery_method,
                    order_value=sale_price
                )
                
                if billing_summary.get("success"):
                    result["commission"] = billing_summary["commission"]
                    result["listing_fee"] = billing_summary["listing_fee"]
                    result["shipping_fee"] = billing_summary["shipping_fee"]
                    result["promo_fee"] = billing_summary["promo_fee"]
                    result["other_fees"] = billing_summary["other_fees"]
                    result["billing_entries"] = billing_summary["entries"]
                    result["fee_details"] = billing_summary.get("fee_details", [])
                    result["estimated_shipping"] = billing_summary.get("estimated_shipping")
                    result["billing_data_available"] = True
                    
                    # Jesli koszt wysylki jest szacowany, uzyj go
                    if result["shipping_fee"] == Decimal("0") and billing_summary.get("shipping_fee_estimated"):
                        result["shipping_fee"] = billing_summary["shipping_fee_estimated"]
                    
                    logger.info(
                        f"Pobrano dane billingowe dla zamowienia {order.order_id} "
                        f"(Allegro: {allegro_order_id}): prowizja={result['commission']}, "
                        f"wysylka={result['shipping_fee']}"
                    )
                else:
                    logger.warning(
                        f"Nie udalo sie pobrac danych billingowych dla {order.order_id}: "
                        f"{billing_summary.get('error')}"
                    )
        except Exception as e:
            logger.warning(f"Blad podczas pobierania danych billingowych dla {order.order_id}: {e}")
        
        # Fallback - szacunki
        if not result["billing_data_available"]:
            result["commission"] = sale_price * Decimal("0.123")  # 12.3%
        
        return result
    
    def calculate_purchase_cost(self, order: Order) -> Decimal:
        """Oblicz koszt zakupu produktow w zamowieniu."""
        purchase_cost = Decimal("0")
        
        for op in order.products:
            if op.product_size and op.product_size.product:
                latest_batch = (
                    self.db.query(PurchaseBatch)
                    .filter(
                        PurchaseBatch.product_id == op.product_size.product_id,
                        PurchaseBatch.size == op.product_size.size
                    )
                    .order_by(desc(PurchaseBatch.purchase_date))
                    .first()
                )
                if latest_batch:
                    purchase_cost += Decimal(str(latest_batch.price)) * op.quantity
        
        return purchase_cost
    
    def build_status_history(self, order_id: str) -> tuple[list[dict], dict]:
        """
        Buduj historie statusow zamowienia.
        
        Returns:
            tuple: (status_history, current_status)
        """
        status_logs = (
            self.db.query(OrderStatusLog)
            .filter(OrderStatusLog.order_id == order_id)
            .order_by(desc(OrderStatusLog.timestamp))
            .all()
        )
        
        status_history = []
        seen_statuses = set()
        
        for log in status_logs:
            if log.status in seen_statuses:
                continue
            seen_statuses.add(log.status)
            
            status_text, status_class = STATUS_DISPLAY_MAP.get(
                log.status, (log.status, "bg-secondary")
            )
            status_history.append({
                "status": log.status,
                "status_text": status_text,
                "status_class": status_class,
                "timestamp": log.timestamp,
                "tracking_number": log.tracking_number,
                "courier_code": log.courier_code,
                "notes": log.notes,
            })
        
        current_status = status_history[0] if status_history else {
            "status": "niewydrukowano",
            "status_text": "Niewydrukowano",
            "status_class": "bg-secondary",
        }
        
        return status_history, current_status
    
    def get_current_stage_index(self, current_status: dict) -> int:
        """Zwroc indeks aktualnego etapu wysylki."""
        current_stage_key = current_status.get("status", "pobrano")
        stage_keys = [s[0] for s in SHIPPING_STAGES]
        
        if current_stage_key in stage_keys:
            return stage_keys.index(current_stage_key)
        return -1
    
    def build_return_info(self, order_id: str) -> tuple[Optional[dict], list[dict], int]:
        """
        Buduj informacje o zwrocie dla zamowienia.
        
        Returns:
            tuple: (return_info, return_status_history, return_stage_index)
        """
        active_return = self.db.query(Return).filter(
            Return.order_id == order_id,
            Return.status != "cancelled"
        ).order_by(desc(Return.created_at)).first()
        
        if not active_return:
            return None, [], -1
        
        status_text, status_class = RETURN_STATUS_MAP.get(
            active_return.status, 
            (active_return.status, "bg-secondary")
        )
        
        # Parsuj items_json
        return_items = []
        if active_return.items_json:
            try:
                return_items = json.loads(active_return.items_json)
            except (json.JSONDecodeError, TypeError):
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
        return_status_history = []
        return_logs = self.db.query(ReturnStatusLog).filter(
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
        
        # Indeks etapu zwrotu
        return_stage_keys = [s[0] for s in RETURN_STAGES]
        return_stage_index = -1
        if active_return.status in return_stage_keys:
            return_stage_index = return_stage_keys.index(active_return.status)
        
        return return_info, return_status_history, return_stage_index
    
    def build_full_context(self, order: Order) -> dict:
        """
        Buduj pelny kontekst dla widoku szczegolów zamówienia.
        
        Returns:
            dict ze wszystkimi danymi potrzebnymi do renderowania szablonu
        """
        # Produkty
        products = self.build_products_list(order)
        
        # Cena sprzedazy
        sale_price = Decimal(str(order.payment_done)) if order.payment_done else Decimal("0")
        
        # Koszt pakowania
        try:
            packaging_cost = Decimal(str(settings_store.get("PACKAGING_COST") or "0.16"))
        except (ValueError, TypeError):
            packaging_cost = Decimal("0.16")
        
        # Dane billingowe
        billing = self.fetch_billing_data(order, sale_price)
        
        # Koszt zakupu
        purchase_cost = self.calculate_purchase_cost(order)
        
        # Suma oplat Allegro
        total_allegro_fees = (
            billing["commission"] + 
            billing["listing_fee"] + 
            billing["shipping_fee"] + 
            billing["promo_fee"] + 
            billing["other_fees"]
        )
        
        # Zysk
        real_profit = sale_price - total_allegro_fees - purchase_cost - packaging_cost
        
        # Historia statusow
        status_history, current_status = self.build_status_history(order.order_id)
        current_stage_index = self.get_current_stage_index(current_status)
        
        # Informacje o zwrocie
        return_info, return_status_history, return_stage_index = self.build_return_info(order.order_id)
        
        return {
            "order": order,
            "products": products,
            "status_history": status_history,
            "current_status": current_status,
            "allegro_commission": billing["commission"],
            "listing_fee": billing["listing_fee"],
            "allegro_shipping_fee": billing["shipping_fee"],
            "promo_fee": billing["promo_fee"],
            "other_fees": billing["other_fees"],
            "total_allegro_fees": total_allegro_fees,
            "billing_data_available": billing["billing_data_available"],
            "billing_entries": billing["billing_entries"],
            "fee_details": billing["fee_details"],
            "purchase_cost": purchase_cost,
            "packaging_cost": packaging_cost,
            "real_profit": real_profit,
            "shipping_stages": SHIPPING_STAGES,
            "current_stage_index": current_stage_index,
            "return_info": return_info,
            "return_status_history": return_status_history,
            "return_stages": RETURN_STAGES,
            "return_stage_index": return_stage_index,
        }


def build_order_detail_context(db_session, order: Order) -> dict:
    """
    Wrapper funkcji dla kompatybilnosci.
    
    Usage:
        with get_session() as db:
            order = db.query(Order).filter(...).first()
            context = build_order_detail_context(db, order)
            return render_template("order_detail.html", **context)
    """
    builder = OrderDetailBuilder(db_session)
    return builder.build_full_context(order)
