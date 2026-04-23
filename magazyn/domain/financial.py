"""
Modul odpowiedzialny za wszystkie kalkulacje finansowe.

Centralizuje logike obliczania:
- Kosztow zakupu
- Oplat Allegro
- Zysku z zamowien
- Podsumowania okresowego
"""

import json as _json
from datetime import datetime
from decimal import Decimal
import logging
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from sqlalchemy import desc
from sqlalchemy import or_ as db_or
from sqlalchemy.orm import Session


logger = logging.getLogger(__name__)


@dataclass
class ProfitBreakdown:
    """Struktura reprezentujaca rozbicie zysku z zamowienia."""
    order_id: str
    sale_price: Decimal
    allegro_fees: Decimal
    purchase_cost: Decimal
    packaging_cost: Decimal
    profit: Decimal
    fee_source: str  # 'api' lub 'estimated'
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'order_id': self.order_id,
            'sale_price': float(self.sale_price),
            'allegro_fees': float(self.allegro_fees),
            'purchase_cost': float(self.purchase_cost),
            'packaging_cost': float(self.packaging_cost),
            'profit': float(self.profit),
            'fee_source': self.fee_source,
        }


@dataclass
class PeriodSummary:
    """Struktura reprezentujaca podsumowanie finansowe za okres."""
    start_date: int  # timestamp
    end_date: int  # timestamp
    orders_count: int
    products_sold: int
    total_revenue: Decimal
    total_purchase_cost: Decimal
    total_allegro_fees: Decimal
    total_packaging_cost: Decimal
    gross_profit: Decimal
    fixed_costs: Decimal
    net_profit: Decimal
    fixed_costs_list: List[Dict[str, Any]]
    returns_count: int = 0
    returned_qty: int = 0
    returns_list: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'orders_count': self.orders_count,
            'products_sold': self.products_sold,
            'total_revenue': float(self.total_revenue),
            'total_purchase_cost': float(self.total_purchase_cost),
            'total_allegro_fees': float(self.total_allegro_fees),
            'total_packaging_cost': float(self.total_packaging_cost),
            'gross_profit': float(self.gross_profit),
            'fixed_costs': float(self.fixed_costs),
            'net_profit': float(self.net_profit),
            'fixed_costs_list': self.fixed_costs_list,
            'returns_count': self.returns_count,
            'returned_qty': self.returned_qty,
            'returns_list': self.returns_list,
        }


class FinancialCalculator:
    """
    Centralna klasa do wszystkich kalkulacji finansowych.
    
    Uzycie:
        from magazyn.domain.financial import FinancialCalculator
        
        calculator = FinancialCalculator(db_session, settings_store)
        profit = calculator.calculate_order_profit(order)
        summary = calculator.get_period_summary(start_ts, end_ts)
    """
    
    # Domyslna prowizja Allegro (12.3%)
    DEFAULT_ALLEGRO_FEE_RATE = Decimal("0.123")
    # Domyslny koszt wysylki do szacowania oplat
    DEFAULT_SHIPPING_COST = Decimal("8.99")
    
    def __init__(self, db_session: Session, settings_store=None):
        """
        Args:
            db_session: Sesja SQLAlchemy
            settings_store: Obiekt settings_store z konfiguracja (opcjonalny)
        """
        self.db = db_session
        self.settings = settings_store
    
    def get_packaging_cost(self) -> Decimal:
        """Pobiera koszt pakowania z ustawien."""
        if self.settings:
            cost = self.settings.get("PACKAGING_COST")
            if cost:
                return Decimal(str(cost))
        return Decimal("0.16")
    
    def get_purchase_cost_for_product(
        self, 
        product_id: int, 
        size: str, 
        quantity: int = 1
    ) -> Decimal:
        """
        Pobiera koszt zakupu dla produktu.
        
        Args:
            product_id: ID produktu
            size: Rozmiar produktu
            quantity: Ilosc sztuk
            
        Returns:
            Koszt zakupu (cena jednostkowa * ilosc)
        """
        from ..models import PurchaseBatch
        
        latest_batch = (
            self.db.query(PurchaseBatch)
            .filter(
                PurchaseBatch.product_id == product_id,
                PurchaseBatch.size == size
            )
            .order_by(desc(PurchaseBatch.purchase_date))
            .first()
        )
        
        if latest_batch:
            return Decimal(str(latest_batch.price)) * quantity
        return Decimal("0")
    
    def get_purchase_cost_for_order(self, order_id: str) -> Decimal:
        """
        Oblicza calkowity koszt zakupu dla zamowienia.
        
        Uzywa dwoch sciezek powiazania:
        1. Bezposrednie: OrderProduct.product_size_id -> ProductSize
        2. Przez Allegro: OrderProduct.auction_id -> AllegroOffer.product_size_id
        
        Args:
            order_id: ID zamowienia
            
        Returns:
            Suma kosztow zakupu dla wszystkich produktow w zamowieniu
        """
        from ..models import OrderProduct, AllegroOffer
        
        total_cost = Decimal("0")
        order_products = self.db.query(OrderProduct).filter(
            OrderProduct.order_id == order_id
        ).all()
        
        for op in order_products:
            product_size = op.product_size
            
            # Fallback przez allegro_offers
            if not product_size and op.auction_id:
                allegro_offer = self.db.query(AllegroOffer).filter(
                    AllegroOffer.offer_id == op.auction_id
                ).first()
                if allegro_offer and allegro_offer.product_size:
                    product_size = allegro_offer.product_size
            
            if product_size and product_size.product:
                cost = self.get_purchase_cost_for_product(
                    product_size.product_id,
                    product_size.size,
                    op.quantity
                )
                total_cost += cost
        
        return total_cost
    
    def get_allegro_fees(
        self, 
        external_order_id: str, 
        sale_price: Decimal,
        access_token: Optional[str] = None,
        delivery_method: Optional[str] = None
    ) -> tuple[Decimal, str]:
        """
        Pobiera oplaty Allegro dla zamowienia.
        
        Najpierw probuje pobrac rzeczywiste oplaty z API,
        jesli to sie nie uda - szacuje na podstawie prowizji.
        
        Args:
            external_order_id: UUID zamowienia Allegro (external_order_id)
            sale_price: Cena sprzedazy
            access_token: Token dostepu Allegro (opcjonalny)
            delivery_method: Metoda dostawy do szacowania kosztu wysylki
            
        Returns:
            Tuple (oplaty, zrodlo) gdzie zrodlo to 'api' lub 'estimated'
        """
        billing_started_at = time.perf_counter()

        # Probuj pobrac z API
        if access_token and external_order_id:
            try:
                from ..allegro_api import get_order_billing_summary
                billing = get_order_billing_summary(
                    access_token,
                    external_order_id,
                )
                if billing and billing.get("success") and billing.get("total_fees"):
                    fees = Decimal(str(billing["total_fees"]))
                    elapsed_ms = (time.perf_counter() - billing_started_at) * 1000
                    logger.info(
                        "Profit billing API success: order_external_id=%s fees=%s entries=%s elapsed_ms=%.1f estimated_shipping=%s",
                        external_order_id,
                        fees,
                        len(billing.get("entries") or []),
                        elapsed_ms,
                        bool(billing.get("estimated_shipping")),
                    )
                    return (fees, 'api')
                elapsed_ms = (time.perf_counter() - billing_started_at) * 1000
                logger.warning(
                    "Profit billing API fallback: order_external_id=%s reason=empty_or_unsuccessful elapsed_ms=%.1f success=%s error=%s",
                    external_order_id,
                    elapsed_ms,
                    billing.get("success") if isinstance(billing, dict) else None,
                    billing.get("error") if isinstance(billing, dict) else None,
                )
            except Exception as exc:
                elapsed_ms = (time.perf_counter() - billing_started_at) * 1000
                logger.warning(
                    "Profit billing API exception: order_external_id=%s elapsed_ms=%.1f error=%s",
                    external_order_id,
                    elapsed_ms,
                    exc,
                )
        
        # Fallback - szacunkowa prowizja
        fees = sale_price * self.DEFAULT_ALLEGRO_FEE_RATE
        
        # Dodaj szacowany koszt wysylki
        shipping_cost = self._estimate_shipping_cost(delivery_method)
        fees += shipping_cost
        
        return (fees, 'estimated')
    
    def _estimate_shipping_cost(self, delivery_method: Optional[str] = None) -> Decimal:
        """Szacuje koszt wysylki na podstawie metody dostawy."""
        if not delivery_method:
            return self.DEFAULT_SHIPPING_COST
        
        try:
            from ..allegro_api import estimate_allegro_shipping_cost
            return estimate_allegro_shipping_cost(delivery_method)
        except Exception:
            return self.DEFAULT_SHIPPING_COST
    
    def calculate_order_profit(
        self, 
        order,
        access_token: Optional[str] = None,
        trace_label: Optional[str] = None,
    ) -> ProfitBreakdown:
        """
        Oblicza pelny rozklad zysku dla zamowienia.
        
        Args:
            order: Obiekt Order
            access_token: Token Allegro do pobierania rzeczywistych oplat
            
        Returns:
            ProfitBreakdown ze szczegolami kalkulacji
        """
        order_started_at = time.perf_counter()

        # Cena sprzedazy - dla pobrania (COD) uzywamy kwoty zamowienia
        payment_method_cod = getattr(order, 'payment_method_cod', False)
        payment_method_str = str(getattr(order, 'payment_method', '') or '')
        is_cod = bool(payment_method_cod) or 'pobranie' in payment_method_str.lower()
        if is_cod and hasattr(order, 'products'):
            try:
                products_total = sum(
                    Decimal(str(p.price_brutto or 0)) * p.quantity
                    for p in order.products
                )
                delivery = Decimal(str(getattr(order, 'delivery_price', None) or 0))
                sale_price = products_total + delivery
            except Exception:
                sale_price = Decimal(str(order.payment_done or 0))
        else:
            sale_price = Decimal(str(order.payment_done or 0))
        
        # Oplaty Allegro - uzyj external_order_id dla billing API
        delivery_method = getattr(order, 'delivery_method', None)
        external_order_id = getattr(order, 'external_order_id', None)
        allegro_fees, fee_source = self.get_allegro_fees(
            external_order_id,
            sale_price,
            access_token,
            delivery_method
        )
        
        # Koszt zakupu
        purchase_cost = self.get_purchase_cost_for_order(order.order_id)
        
        # Koszt pakowania
        packaging_cost = self.get_packaging_cost()
        
        # Zysk
        profit = sale_price - allegro_fees - purchase_cost - packaging_cost

        elapsed_ms = (time.perf_counter() - order_started_at) * 1000
        order_id = getattr(order, 'order_id', None)
        logger.info(
            "Profit order calculated: trace=%s order_id=%s external_order_id=%s sale_price=%s fees=%s fee_source=%s purchase_cost=%s packaging_cost=%s profit=%s elapsed_ms=%.1f",
            trace_label or '-',
            order_id,
            external_order_id,
            sale_price,
            allegro_fees,
            fee_source,
            purchase_cost,
            packaging_cost,
            profit,
            elapsed_ms,
        )
        
        return ProfitBreakdown(
            order_id=order.order_id,
            sale_price=sale_price,
            allegro_fees=allegro_fees,
            purchase_cost=purchase_cost,
            packaging_cost=packaging_cost,
            profit=profit,
            fee_source=fee_source
        )
    
    def get_period_summary(
        self,
        start_timestamp: int,
        end_timestamp: int,
        include_fixed_costs: bool = True,
        access_token: Optional[str] = None,
        trace_label: Optional[str] = None,
    ) -> PeriodSummary:
        """
        Generuje podsumowanie finansowe za okres.
        
        Args:
            start_timestamp: Poczatek okresu (Unix timestamp)
            end_timestamp: Koniec okresu (Unix timestamp)
            include_fixed_costs: Czy odejmowac koszty stale
            access_token: Token Allegro do pobierania rzeczywistych oplat
            
        Returns:
            PeriodSummary z pelnym podsumowaniem
        """
        from ..models import Order, OrderProduct, Return, FixedCost
        from sqlalchemy import func, select

        total_started_at = time.perf_counter()
        logger.info(
            "Profit period summary start: trace=%s start_ts=%s end_ts=%s include_fixed_costs=%s access_token=%s",
            trace_label or '-',
            start_timestamp,
            end_timestamp,
            include_fixed_costs,
            bool(access_token),
        )

        # Wyklucz zamowienia ze zwrotem zakonczonym (status=completed)
        return_order_ids = select(Return.order_id).where(
            Return.status == 'completed'
        ).distinct()

        orders_query_started_at = time.perf_counter()
        orders = self.db.query(Order).filter(
            Order.date_add >= start_timestamp,
            Order.date_add < end_timestamp,
            ~Order.order_id.in_(return_order_ids)
        ).filter(
            # Zamowienia z platnoscia LUB za pobraniem (payment_done=0 ale COD)
            db_or(
                Order.payment_done > 0,
                Order.payment_method_cod == True,
            )
        ).all()
        orders_query_ms = (time.perf_counter() - orders_query_started_at) * 1000

        # Zlicz produkty
        products_query_started_at = time.perf_counter()
        products_sold = self.db.query(func.sum(OrderProduct.quantity)).join(
            Order, Order.order_id == OrderProduct.order_id
        ).filter(
            Order.date_add >= start_timestamp,
            Order.date_add < end_timestamp,
        ).filter(
            db_or(
                Order.payment_done > 0,
                Order.payment_method_cod == True,
            )
        ).scalar() or 0
        products_query_ms = (time.perf_counter() - products_query_started_at) * 1000

        # Zwroty zakonczone w tym okresie (wg updated_at - kiedy status zmieniono na completed)
        start_dt_str = datetime.fromtimestamp(start_timestamp).strftime('%Y-%m-%d %H:%M:%S')
        end_dt_str = datetime.fromtimestamp(end_timestamp).strftime('%Y-%m-%d %H:%M:%S')
        returns_query_started_at = time.perf_counter()
        returns_in_period = self.db.query(Return).filter(
            Return.status == 'completed',
            Return.updated_at >= start_dt_str,
            Return.updated_at < end_dt_str,
        ).all()
        returns_query_ms = (time.perf_counter() - returns_query_started_at) * 1000
        returns_count = len(returns_in_period)
        returned_qty = 0
        returns_list = []
        for ret in returns_in_period:
            items = _json.loads(ret.items_json or '[]')
            ret_qty = sum(item.get('quantity', 1) for item in items)
            returned_qty += ret_qty
            returns_list.append({
                'order_id': ret.order_id,
                'customer_name': ret.customer_name or '',
                'items': [
                    {'name': i.get('name', ''), 'quantity': i.get('quantity', 1)}
                    for i in items
                ],
                'qty': ret_qty,
                'updated_at': str(ret.updated_at)[:10] if ret.updated_at else '',
            })

        logger.info(
            "Profit period summary loaded inputs: trace=%s orders=%s products_sold=%s returns=%s orders_query_ms=%.1f products_query_ms=%.1f returns_query_ms=%.1f",
            trace_label or '-',
            len(orders),
            products_sold,
            returns_count,
            orders_query_ms,
            products_query_ms,
            returns_query_ms,
        )
        
        # Kalkuluj dla kazdego zamowienia
        total_revenue = Decimal("0")
        total_purchase_cost = Decimal("0")
        total_allegro_fees = Decimal("0")
        packaging_cost = self.get_packaging_cost()
        total_packaging_cost = Decimal("0")
        api_fee_orders = 0
        estimated_fee_orders = 0
        slow_orders = 0
        slow_order_ids: list[str] = []
        loop_started_at = time.perf_counter()
        
        for order in orders:
            breakdown = self.calculate_order_profit(order, access_token, trace_label=trace_label)
            total_revenue += breakdown.sale_price
            total_purchase_cost += breakdown.purchase_cost
            total_allegro_fees += breakdown.allegro_fees
            total_packaging_cost += packaging_cost
            if breakdown.fee_source == 'api':
                api_fee_orders += 1
            else:
                estimated_fee_orders += 1
            if breakdown.fee_source == 'api' and getattr(breakdown, 'profit', None) is not None:
                pass
        loop_elapsed_ms = (time.perf_counter() - loop_started_at) * 1000

        if loop_elapsed_ms > 5000:
            logger.warning(
                "Profit period summary slow loop: trace=%s orders=%s api_fee_orders=%s estimated_fee_orders=%s elapsed_ms=%.1f",
                trace_label or '-',
                len(orders),
                api_fee_orders,
                estimated_fee_orders,
                loop_elapsed_ms,
            )
        else:
            logger.info(
                "Profit period summary loop done: trace=%s orders=%s api_fee_orders=%s estimated_fee_orders=%s elapsed_ms=%.1f",
                trace_label or '-',
                len(orders),
                api_fee_orders,
                estimated_fee_orders,
                loop_elapsed_ms,
            )
        
        # Zysk brutto
        gross_profit = total_revenue - total_allegro_fees - total_purchase_cost - total_packaging_cost
        
        # Koszty stale
        fixed_costs = Decimal("0")
        fixed_costs_list = []
        
        if include_fixed_costs:
            fixed_costs_started_at = time.perf_counter()
            fc_query = self.db.query(FixedCost).filter(FixedCost.is_active == True).all()
            for fc in fc_query:
                fixed_costs += Decimal(str(fc.amount))
                fixed_costs_list.append({
                    'name': fc.name,
                    'amount': float(fc.amount)
                })
            logger.info(
                "Profit period summary fixed costs loaded: trace=%s count=%s total=%s elapsed_ms=%.1f",
                trace_label or '-',
                len(fc_query),
                fixed_costs,
                (time.perf_counter() - fixed_costs_started_at) * 1000,
            )
        
        # Zysk netto
        net_profit = gross_profit - fixed_costs

        total_elapsed_ms = (time.perf_counter() - total_started_at) * 1000
        logger.info(
            "Profit period summary done: trace=%s orders=%s revenue=%s purchase_cost=%s allegro_fees=%s packaging=%s gross_profit=%s fixed_costs=%s net_profit=%s total_elapsed_ms=%.1f",
            trace_label or '-',
            len(orders),
            total_revenue,
            total_purchase_cost,
            total_allegro_fees,
            total_packaging_cost,
            gross_profit,
            fixed_costs,
            net_profit,
            total_elapsed_ms,
        )
        
        return PeriodSummary(
            start_date=start_timestamp,
            end_date=end_timestamp,
            orders_count=len(orders),
            products_sold=int(products_sold),
            total_revenue=total_revenue,
            total_purchase_cost=total_purchase_cost,
            total_allegro_fees=total_allegro_fees,
            total_packaging_cost=total_packaging_cost,
            gross_profit=gross_profit,
            fixed_costs=fixed_costs,
            net_profit=net_profit,
            fixed_costs_list=fixed_costs_list,
            returns_count=returns_count,
            returned_qty=returned_qty,
            returns_list=returns_list,
        )


# Funkcje pomocnicze dla kompatybilnosci wstecznej

def get_order_profit(db_session: Session, order, settings_store=None, access_token=None) -> Dict:
    """
    Funkcja pomocnicza - oblicza zysk z zamowienia.
    
    Dla kompatybilnosci wstecznej - preferuj uzycie FinancialCalculator.
    """
    calculator = FinancialCalculator(db_session, settings_store)
    breakdown = calculator.calculate_order_profit(order, access_token)
    return breakdown.to_dict()


def get_period_financial_summary(
    db_session: Session, 
    start_ts: int, 
    end_ts: int, 
    settings_store=None,
    include_fixed_costs: bool = True,
    access_token: str = None
) -> Dict:
    """
    Funkcja pomocnicza - generuje podsumowanie finansowe.
    
    Dla kompatybilnosci wstecznej - preferuj uzycie FinancialCalculator.
    """
    calculator = FinancialCalculator(db_session, settings_store)
    summary = calculator.get_period_summary(
        start_ts, 
        end_ts, 
        include_fixed_costs,
        access_token
    )
    return summary.to_dict()
