"""
Serwis dashboardu - centralizacja logiki pobierania danych dla strony glownej.

Wyodrebniony z app.py dla lepszej organizacji kodu.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import func, desc
from sqlalchemy.orm import Session, joinedload

from ..models import (
    Order, OrderProduct, Product, ProductSize, 
    PurchaseBatch, AllegroOffer, Return
)
from .financial import FinancialCalculator


MONTH_NAMES = [
    'Styczen', 'Luty', 'Marzec', 'Kwiecien', 'Maj', 'Czerwiec',
    'Lipiec', 'Sierpien', 'Wrzesien', 'Pazdziernik', 'Listopad', 'Grudzien'
]


@dataclass
class TimeRanges:
    """Zakresy czasowe dla dashboardu."""
    now: datetime
    today_start: int
    week_start_ts: int
    month_start_ts: int
    prev_week_start_ts: int
    current_month_name: str
    
    @classmethod
    def create(cls) -> "TimeRanges":
        """Tworzy zakresy czasowe dla biezacego momentu."""
        now = datetime.now()
        today_start = int(now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
        
        week_start = now - timedelta(days=now.weekday())
        week_start_ts = int(week_start.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
        
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        month_start_ts = int(month_start.timestamp())
        
        prev_week_start_ts = int((week_start - timedelta(days=7)).timestamp())
        
        return cls(
            now=now,
            today_start=today_start,
            week_start_ts=week_start_ts,
            month_start_ts=month_start_ts,
            prev_week_start_ts=prev_week_start_ts,
            current_month_name=MONTH_NAMES[now.month - 1]
        )


@dataclass
class OrderStats:
    """Statystyki zamowien."""
    today: int = 0
    week: int = 0
    month: int = 0
    pending: int = 0


@dataclass
class RevenueStats:
    """Statystyki przychodow."""
    today: float = 0.0
    week: float = 0.0
    month: float = 0.0


@dataclass
class InventoryStats:
    """Statystyki magazynowe."""
    total_products: int = 0
    total_stock: int = 0
    out_of_stock: int = 0
    low_stock_items: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class AllegroStats:
    """Statystyki ofert Allegro."""
    total_offers: int = 0
    unlinked_offers: int = 0


@dataclass
class TrendStats:
    """Statystyki trendow."""
    orders_change: float = 0.0
    revenue_change: float = 0.0
    prev_week_orders: int = 0
    prev_week_revenue: float = 0.0


class DashboardService:
    """
    Serwis do pobierania danych dashboardu.
    
    Uzycie:
        with get_session() as db:
            service = DashboardService(db, settings_store)
            dashboard = service.get_full_dashboard()
    """
    
    def __init__(self, db: Session, settings_store: Any):
        self.db = db
        self.settings = settings_store
        self.time_ranges = TimeRanges.create()
    
    def get_order_stats(self) -> OrderStats:
        """Pobiera statystyki zamowien."""
        tr = self.time_ranges
        
        orders_today = self.db.query(Order).filter(
            Order.date_add >= tr.today_start
        ).count()
        
        orders_week = self.db.query(Order).filter(
            Order.date_add >= tr.week_start_ts
        ).count()
        
        orders_month = self.db.query(Order).filter(
            Order.date_add >= tr.month_start_ts
        ).count()
        
        pending_orders = self.db.query(Order).filter(
            Order.delivery_package_nr.is_(None),
            Order.date_add >= tr.month_start_ts
        ).count()
        
        return OrderStats(
            today=orders_today,
            week=orders_week,
            month=orders_month,
            pending=pending_orders
        )
    
    def get_revenue_stats(self) -> RevenueStats:
        """Pobiera statystyki przychodow."""
        tr = self.time_ranges
        
        def calc_revenue(from_timestamp: int) -> float:
            result = self.db.query(
                func.sum(OrderProduct.price_brutto * OrderProduct.quantity)
            ).join(Order).filter(Order.date_add >= from_timestamp).scalar()
            return float(result or 0)
        
        return RevenueStats(
            today=calc_revenue(tr.today_start),
            week=calc_revenue(tr.week_start_ts),
            month=calc_revenue(tr.month_start_ts)
        )
    
    def get_profit_stats(self, access_token: Optional[str] = None) -> Dict[str, Any]:
        """Pobiera statystyki zysku uzywajac FinancialCalculator."""
        tr = self.time_ranges
        calculator = FinancialCalculator(self.db, self.settings)
        
        now_ts = int(tr.now.timestamp())
        summary = calculator.get_period_summary(
            tr.month_start_ts,
            now_ts,
            include_fixed_costs=True,
            access_token=access_token
        )
        
        # Policz zwroty
        returned_order_ids = set(
            r.order_id for r in self.db.query(Return.order_id).filter(
                Return.status.in_(['completed', 'delivered', 'in_transit', 'pending'])
            ).all()
        )
        total_returned_orders = self.db.query(Order).filter(
            Order.date_add >= tr.month_start_ts,
            Order.order_id.in_(returned_order_ids)
        ).count() if returned_order_ids else 0
        
        return {
            'month': float(summary.net_profit),
            'month_before_fixed': float(summary.gross_profit),
            'fixed_costs': float(summary.fixed_costs),
            'fixed_costs_list': summary.fixed_costs_list,
            'products_sold': summary.products_sold,
            'returned_orders': total_returned_orders,
        }
    
    def get_inventory_stats(self) -> InventoryStats:
        """Pobiera statystyki magazynowe."""
        total_products = self.db.query(Product).count()
        total_stock = self.db.query(func.sum(ProductSize.quantity)).scalar() or 0
        out_of_stock = self.db.query(ProductSize).filter(ProductSize.quantity == 0).count()
        
        # Niski stan (1-2 szt.)
        low_stock_query = self.db.query(ProductSize, Product)\
            .join(Product)\
            .filter(ProductSize.quantity > 0, ProductSize.quantity <= 2)\
            .order_by(ProductSize.quantity.asc())\
            .limit(10)\
            .all()
        
        low_stock_items = [
            {
                'size': size.size,
                'quantity': size.quantity,
                'product_id': product.id,
                'product_name': product.name,
                'product_color': product.color,
            }
            for size, product in low_stock_query
        ]
        
        return InventoryStats(
            total_products=total_products,
            total_stock=total_stock,
            out_of_stock=out_of_stock,
            low_stock_items=low_stock_items
        )
    
    def get_allegro_stats(self) -> AllegroStats:
        """Pobiera statystyki ofert Allegro."""
        total_offers = self.db.query(AllegroOffer).filter(
            AllegroOffer.publication_status == 'ACTIVE'
        ).count()
        
        unlinked_offers = self.db.query(AllegroOffer).filter(
            AllegroOffer.publication_status == 'ACTIVE',
            AllegroOffer.product_size_id.is_(None),
            AllegroOffer.product_id.is_(None)
        ).count()
        
        return AllegroStats(
            total_offers=total_offers,
            unlinked_offers=unlinked_offers
        )
    
    def get_latest_orders(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Pobiera ostatnie zamowienia."""
        latest_orders_query = self.db.query(Order)\
            .options(joinedload(Order.products))\
            .order_by(desc(Order.date_add))\
            .limit(limit)\
            .all()
        
        return [
            {
                'order_id': order.order_id,
                'customer_name': order.customer_name,
                'date_add': order.date_add,
                'delivery_package_nr': order.delivery_package_nr,
                'products_count': len(order.products) if order.products else 0,
                'product_names': [p.name for p in order.products[:2]] if order.products else [],
            }
            for order in latest_orders_query
        ]
    
    def get_latest_deliveries(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Pobiera ostatnie dostawy (zgrupowane po dacie/fakturze)."""
        delivery_groups = self.db.query(
            PurchaseBatch.purchase_date,
            PurchaseBatch.invoice_number,
            PurchaseBatch.supplier,
            func.count(PurchaseBatch.id).label('batch_count'),
            func.sum(PurchaseBatch.quantity).label('total_quantity'),
            func.sum(PurchaseBatch.quantity * PurchaseBatch.price).label('total_value')
        )\
        .group_by(PurchaseBatch.purchase_date, PurchaseBatch.invoice_number, PurchaseBatch.supplier)\
        .order_by(desc(PurchaseBatch.purchase_date))\
        .limit(limit)\
        .all()
        
        latest_deliveries = []
        for date, invoice, supplier, batch_count, total_qty, total_value in delivery_groups:
            if not total_qty or total_qty == 0 or not total_value or total_value == 0:
                continue
            if not date or date == '0000-00-00':
                continue
            
            # Szczegoly produktow w dostawie
            products_in_delivery = self.db.query(PurchaseBatch, Product)\
                .join(Product)\
                .filter(
                    PurchaseBatch.purchase_date == date,
                    PurchaseBatch.invoice_number == invoice,
                    PurchaseBatch.supplier == supplier
                )\
                .all()
            
            product_details = [
                {
                    'product_id': product.id,
                    'name': product.name,
                    'color': product.color,
                    'size': batch.size,
                    'quantity': batch.quantity,
                    'price': batch.price,
                    'value': batch.quantity * batch.price
                }
                for batch, product in products_in_delivery
            ]
            
            latest_deliveries.append({
                'purchase_date': date,
                'invoice_number': invoice,
                'supplier': supplier,
                'batch_count': batch_count,
                'total_quantity': total_qty,
                'total_value': total_value,
                'products': product_details,
            })
        
        return latest_deliveries
    
    def get_bestsellers(
        self, 
        from_timestamp: Optional[int] = None, 
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Pobiera najlepiej sprzedajace sie produkty."""
        query = self.db.query(
            OrderProduct.name.label('order_name'),
            OrderProduct.ean,
            func.sum(OrderProduct.quantity).label('total_qty'),
            func.sum(OrderProduct.price_brutto * OrderProduct.quantity).label('total_revenue'),
            func.count(func.distinct(OrderProduct.order_id)).label('order_count')
        ).join(Order)
        
        if from_timestamp:
            query = query.filter(Order.date_add >= from_timestamp)
        
        results = query.group_by(OrderProduct.name, OrderProduct.ean)\
            .order_by(desc('total_qty'))\
            .limit(limit)\
            .all()
        
        items = []
        for order_name, ean, qty, revenue, orders in results:
            product_id, series, color, size = self._resolve_product_info(order_name, ean)
            
            # Buduj krotka nazwe
            short_parts = []
            if series:
                short_parts.append(series)
            if color:
                short_parts.append(color)
            if size:
                short_parts.append(size)
            short_name = '/'.join(short_parts) if short_parts else (order_name or 'Brak nazwy')[:30]
            
            items.append({
                'name': order_name or 'Brak nazwy',
                'short_name': short_name,
                'ean': ean,
                'quantity': int(qty or 0),
                'revenue': float(revenue or 0),
                'orders': int(orders or 0),
                'product_id': product_id,
            })
        
        return items
    
    def _resolve_product_info(
        self, 
        order_name: str, 
        ean: Optional[str]
    ) -> tuple:
        """Rozwiazuje informacje o produkcie na podstawie nazwy/EAN."""
        product_id = None
        series = None
        color = None
        size = None
        
        # 1. Szukaj przez barcode/EAN
        if ean:
            ps = self.db.query(ProductSize).filter(ProductSize.barcode == ean).first()
            if ps:
                product_id = ps.product_id
                size = ps.size
                prod = self.db.query(Product).filter(Product.id == ps.product_id).first()
                if prod:
                    series = prod.series
                    color = prod.color
        
        # 2. Fallback: znajdz auction_id i szukaj przez AllegroOffer
        if not product_id:
            op_with_auction = self.db.query(OrderProduct.auction_id)\
                .filter(OrderProduct.name == order_name, OrderProduct.ean == ean)\
                .filter(OrderProduct.auction_id.isnot(None))\
                .first()
            
            if op_with_auction and op_with_auction.auction_id:
                offer = self.db.query(AllegroOffer).filter(
                    AllegroOffer.offer_id == op_with_auction.auction_id
                ).first()
                if offer and offer.product_size_id:
                    ps = self.db.query(ProductSize).filter(ProductSize.id == offer.product_size_id).first()
                    if ps:
                        product_id = ps.product_id
                        size = ps.size
                        prod = self.db.query(Product).filter(Product.id == ps.product_id).first()
                        if prod:
                            series = prod.series
                            color = prod.color
                elif offer and offer.product_id:
                    product_id = offer.product_id
                    prod = self.db.query(Product).filter(Product.id == offer.product_id).first()
                    if prod:
                        series = prod.series
                        color = prod.color
        
        return product_id, series, color, size
    
    def get_slow_movers(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Pobiera wolnoobrotowe produkty (duzy stan, mala sprzedaz)."""
        tr = self.time_ranges
        
        # Subquery: sprzedaz w tym miesiacu per EAN
        recent_sales_subq = self.db.query(
            OrderProduct.ean,
            func.sum(OrderProduct.quantity).label('sold_qty')
        ).join(Order)\
        .filter(Order.date_add >= tr.month_start_ts)\
        .group_by(OrderProduct.ean)\
        .subquery()
        
        slow_movers = self.db.query(
            Product.name,
            Product.color,
            ProductSize.size,
            ProductSize.quantity,
            func.coalesce(recent_sales_subq.c.sold_qty, 0).label('sold_30d')
        ).join(Product)\
        .outerjoin(recent_sales_subq, ProductSize.barcode == recent_sales_subq.c.ean)\
        .filter(
            ProductSize.quantity >= 5,
            func.coalesce(recent_sales_subq.c.sold_qty, 0) < 2
        )\
        .order_by(ProductSize.quantity.desc())\
        .limit(limit)\
        .all()
        
        return [
            {
                'name': name,
                'color': color,
                'size': size,
                'stock': qty,
                'sold_30d': int(sold)
            }
            for name, color, size, qty, sold in slow_movers
        ]
    
    def get_trends(self) -> TrendStats:
        """Pobiera trendy (porownanie z poprzednim tygodniem)."""
        tr = self.time_ranges
        
        prev_week_orders = self.db.query(Order).filter(
            Order.date_add >= tr.prev_week_start_ts,
            Order.date_add < tr.week_start_ts
        ).count()
        
        prev_week_revenue = self.db.query(
            func.sum(OrderProduct.price_brutto * OrderProduct.quantity)
        ).join(Order).filter(
            Order.date_add >= tr.prev_week_start_ts,
            Order.date_add < tr.week_start_ts
        ).scalar() or 0
        
        # Biezacy tydzien
        current_week_orders = self.db.query(Order).filter(
            Order.date_add >= tr.week_start_ts
        ).count()
        
        current_week_revenue = self.db.query(
            func.sum(OrderProduct.price_brutto * OrderProduct.quantity)
        ).join(Order).filter(
            Order.date_add >= tr.week_start_ts
        ).scalar() or 0
        
        orders_change = ((current_week_orders - prev_week_orders) / max(prev_week_orders, 1)) * 100
        revenue_change = ((float(current_week_revenue) - float(prev_week_revenue)) / max(float(prev_week_revenue), 1)) * 100
        
        return TrendStats(
            orders_change=round(orders_change, 1),
            revenue_change=round(revenue_change, 1),
            prev_week_orders=prev_week_orders,
            prev_week_revenue=float(prev_week_revenue)
        )
    
    def get_recent_activity(
        self, 
        latest_orders: List[Dict], 
        latest_deliveries: List[Dict],
        url_for_func: Any,
        limit: int = 8
    ) -> List[Dict[str, Any]]:
        """Buduje liste ostatnich aktywnosci."""
        activities = []
        now = self.time_ranges.now
        
        # Zamowienia
        for order in latest_orders[:5]:
            if order['date_add']:
                order_date = datetime.fromtimestamp(order['date_add'])
                products_str = ", ".join(order['product_names'])
                if order['products_count'] > 2:
                    products_str += f" +{order['products_count'] - 2}"
                activities.append({
                    'type': 'order',
                    'icon': 'bi-cart-check',
                    'color': 'success',
                    'title': f'Nowe zamowienie #{order["order_id"][-6:]}',
                    'description': f'{order["customer_name"] or "Klient"}: {products_str}',
                    'timestamp': order_date,
                    'link': url_for_func('orders.order_detail', order_id=order['order_id'])
                })
        
        # Dostawy
        for delivery in latest_deliveries[:3]:
            try:
                batch_date = datetime.strptime(delivery['purchase_date'], '%Y-%m-%d')
            except:
                batch_date = now
            
            title_suffix = delivery['supplier'] or delivery['invoice_number'] or f"{delivery['total_quantity']} szt."
            
            activities.append({
                'type': 'delivery',
                'icon': 'bi-box-seam',
                'color': 'info',
                'title': f'Dostawa: {title_suffix}',
                'description': f'{delivery["total_quantity"]} szt. za {delivery["total_value"]:.2f} zl ({delivery["batch_count"]} modeli)',
                'timestamp': batch_date,
                'link': url_for_func('products.items')
            })
        
        activities.sort(key=lambda x: x['timestamp'], reverse=True)
        return activities[:limit]
    
    def get_full_dashboard(self, access_token: Optional[str] = None) -> Dict[str, Any]:
        """
        Pobiera kompletne dane dashboardu.
        
        Args:
            access_token: Token Allegro do pobierania oplat
            
        Returns:
            Slownik z wszystkimi danymi dashboardu
        """
        order_stats = self.get_order_stats()
        revenue_stats = self.get_revenue_stats()
        profit_stats = self.get_profit_stats(access_token)
        inventory_stats = self.get_inventory_stats()
        allegro_stats = self.get_allegro_stats()
        trends = self.get_trends()
        
        latest_orders = self.get_latest_orders(10)
        latest_deliveries = self.get_latest_deliveries(5)
        
        bestsellers_all = self.get_bestsellers(limit=10)
        bestsellers_month = self.get_bestsellers(self.time_ranges.month_start_ts, limit=10)
        bestsellers_week = self.get_bestsellers(self.time_ranges.week_start_ts, limit=5)
        
        slow_moving = self.get_slow_movers(10)
        
        return {
            'orders': {
                'today': order_stats.today,
                'week': order_stats.week,
                'month': order_stats.month,
                'pending': order_stats.pending,
            },
            'revenue': {
                'today': revenue_stats.today,
                'week': revenue_stats.week,
                'month': revenue_stats.month,
            },
            'profit': profit_stats,
            'current_month_name': self.time_ranges.current_month_name,
            'inventory': {
                'total_products': inventory_stats.total_products,
                'total_stock': inventory_stats.total_stock,
                'out_of_stock': inventory_stats.out_of_stock,
                'low_stock_items': inventory_stats.low_stock_items,
            },
            'allegro': {
                'total_offers': allegro_stats.total_offers,
                'unlinked_offers': allegro_stats.unlinked_offers,
            },
            'latest_orders': latest_orders,
            'latest_deliveries': latest_deliveries,
            'bestsellers': {
                'all_time': bestsellers_all,
                'month': bestsellers_month,
                'week': bestsellers_week,
            },
            'slow_moving': slow_moving,
            'trends': {
                'orders_change': trends.orders_change,
                'revenue_change': trends.revenue_change,
                'prev_week_orders': trends.prev_week_orders,
                'prev_week_revenue': trends.prev_week_revenue,
            },
        }
