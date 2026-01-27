"""
Modul odpowiedzialny za wszystkie kalkulacje finansowe.

Centralizuje logike obliczania:
- Kosztow zakupu
- Oplat Allegro
- Zysku z zamowien
- Podsumowania okresowego
"""

from decimal import Decimal
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from sqlalchemy import desc
from sqlalchemy.orm import Session


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
        # Probuj pobrac z API
        if access_token and external_order_id:
            try:
                from ..allegro_api import get_order_billing_summary
                billing = get_order_billing_summary(access_token, external_order_id)
                if billing and billing.get("success") and billing.get("total_fees"):
                    fees = Decimal(str(billing["total_fees"]))
                    return (fees, 'api')
            except Exception:
                pass
        
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
        access_token: Optional[str] = None
    ) -> ProfitBreakdown:
        """
        Oblicza pelny rozklad zysku dla zamowienia.
        
        Args:
            order: Obiekt Order
            access_token: Token Allegro do pobierania rzeczywistych oplat
            
        Returns:
            ProfitBreakdown ze szczegolami kalkulacji
        """
        # Cena sprzedazy
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
        access_token: Optional[str] = None
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
        
        # Pobierz zamowienia z wykluczonymi zwrotami (tylko te ze statusem 'completed')
        # completed = refundacja zrealizowana (COMMISSION_REFUNDED/FINISHED w Allegro)
        # Zwroty in_transit/pending/delivered nie sa wykluczane - jeszcze nie zwrocono pieniedzy
        return_order_ids = select(Return.order_id).where(
            Return.status == 'completed'
        ).distinct()
        
        orders = self.db.query(Order).filter(
            Order.date_add >= start_timestamp,
            Order.date_add < end_timestamp,
            Order.payment_done.isnot(None),
            ~Order.order_id.in_(return_order_ids)
        ).all()
        
        # Zlicz produkty
        products_sold = self.db.query(func.sum(OrderProduct.quantity)).join(
            Order, Order.order_id == OrderProduct.order_id
        ).filter(
            Order.date_add >= start_timestamp,
            Order.date_add < end_timestamp,
            Order.payment_done.isnot(None),
            ~Order.order_id.in_(return_order_ids)
        ).scalar() or 0
        
        # Kalkuluj dla kazdego zamowienia
        total_revenue = Decimal("0")
        total_purchase_cost = Decimal("0")
        total_allegro_fees = Decimal("0")
        packaging_cost = self.get_packaging_cost()
        total_packaging_cost = Decimal("0")
        
        for order in orders:
            breakdown = self.calculate_order_profit(order, access_token)
            total_revenue += breakdown.sale_price
            total_purchase_cost += breakdown.purchase_cost
            total_allegro_fees += breakdown.allegro_fees
            total_packaging_cost += packaging_cost
        
        # Zysk brutto
        gross_profit = total_revenue - total_allegro_fees - total_purchase_cost - total_packaging_cost
        
        # Koszty stale
        fixed_costs = Decimal("0")
        fixed_costs_list = []
        
        if include_fixed_costs:
            fc_query = self.db.query(FixedCost).filter(FixedCost.is_active == True).all()
            for fc in fc_query:
                fixed_costs += Decimal(str(fc.amount))
                fixed_costs_list.append({
                    'name': fc.name,
                    'amount': float(fc.amount)
                })
        
        # Zysk netto
        net_profit = gross_profit - fixed_costs
        
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
            fixed_costs_list=fixed_costs_list
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
