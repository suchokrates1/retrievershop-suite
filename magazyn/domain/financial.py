"""
Modul odpowiedzialny za wszystkie kalkulacje finansowe.

Centralizuje logike obliczania:
- Kosztow zakupu
- Oplat Allegro
- Zysku z zamowien
- Podsumowania okresowego
"""

import json as _json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from decimal import Decimal
import logging
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from sqlalchemy import desc
from sqlalchemy import or_ as db_or
from sqlalchemy.orm import Session


logger = logging.getLogger(__name__)


def _decimal_or_none(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


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
    billing_complete: bool = False
    shipping_estimated: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'order_id': self.order_id,
            'sale_price': float(self.sale_price),
            'allegro_fees': float(self.allegro_fees),
            'purchase_cost': float(self.purchase_cost),
            'packaging_cost': float(self.packaging_cost),
            'profit': float(self.profit),
            'fee_source': self.fee_source,
            'billing_complete': self.billing_complete,
            'shipping_estimated': self.shipping_estimated,
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
            Koszt zakupu (srednia wazona cena zakupu * ilosc)
        """
        from ..models.products import ProductSize, PurchaseBatch

        product_size = (
            self.db.query(ProductSize)
            .filter(ProductSize.product_id == product_id, ProductSize.size == size)
            .first()
        )

        # Preferuj biezaca srednia wazona (stock_value / quantity).
        if product_size and product_size.quantity and product_size.stock_value:
            avg = Decimal(str(product_size.stock_value)) / Decimal(product_size.quantity)
            return avg * quantity

        # Fallback: brak stanu/wartosci -> ostatnia znana cena dostawy.
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
    
    def get_purchase_cost_for_order(
        self,
        order_id: str,
        *,
        with_source: bool = False,
    ):
        """
        Oblicza calkowity koszt zakupu dla zamowienia.

        Preferuje REALNY koszt zapisany w Sale.purchase_cost (cena partii FIFO,
        z ktorej towar faktycznie zszedl przy wysylce - patrz
        services/stock_records.py: consume_stock/record_sale). Dziala tylko dla
        produktow powiazanych z Sale przez order_id, czyli zamowien wyslanych
        PO wdrozeniu tego powiazania (starsze Sale nie maja order_id).

        Dla produktow bez takiego powiazania (zamowienie jeszcze niewyslane,
        albo Sale sprzed wdrozenia order_id) spada do starego szacunku: ceny
        NAJNOWSZEJ dostawy danego produktu - patrz get_purchase_cost_for_product.

        Uzywa dwoch sciezek powiazania OrderProduct -> ProductSize:
        1. Bezposrednie: OrderProduct.product_size_id -> ProductSize
        2. Przez Allegro: OrderProduct.auction_id -> AllegroOffer.product_size_id

        Args:
            order_id: ID zamowienia
            with_source: jesli True, zwraca krotke (koszt, czy_w_pelni_realny)

        Returns:
            Suma kosztow zakupu dla wszystkich produktow w zamowieniu (Decimal),
            lub (Decimal, bool) jesli with_source=True.
        """
        from sqlalchemy import func

        from ..models.allegro import AllegroOffer
        from ..models.orders import OrderProduct
        from ..models.products import Sale

        order_products = self.db.query(OrderProduct).filter(
            OrderProduct.order_id == order_id
        ).all()

        actual_by_key: Dict[tuple, Decimal] = {}
        for product_id, size, cost_sum in (
            self.db.query(Sale.product_id, Sale.size, func.sum(Sale.purchase_cost))
            .filter(Sale.order_id == order_id)
            .group_by(Sale.product_id, Sale.size)
            .all()
        ):
            actual_by_key[(product_id, size)] = Decimal(str(cost_sum or 0))

        total_cost = Decimal("0")
        is_fully_actual = bool(actual_by_key) or not order_products

        for op in order_products:
            product_size = op.product_size

            # Fallback przez allegro_offers
            if not product_size and op.auction_id:
                allegro_offer = self.db.query(AllegroOffer).filter(
                    AllegroOffer.offer_id == op.auction_id
                ).first()
                if allegro_offer and allegro_offer.product_size:
                    product_size = allegro_offer.product_size

            if not product_size or not product_size.product:
                continue

            key = (product_size.product_id, product_size.size)
            if key in actual_by_key:
                total_cost += actual_by_key.pop(key)
            else:
                total_cost += self.get_purchase_cost_for_product(
                    product_size.product_id,
                    product_size.size,
                    op.quantity,
                )
                is_fully_actual = False

        # Sale bez odpowiadajacej linii OrderProduct (np. produkt niedopasowany
        # do magazynu przy sprzedazy -> zapisany na koncie placeholdera
        # "Unknown") - to nadal realny, poniesiony koszt, wiec doliczamy.
        for remaining_cost in actual_by_key.values():
            total_cost += remaining_cost

        if with_source:
            return total_cost, is_fully_actual
        return total_cost
    
    def get_allegro_fees(
        self, 
        external_order_id: str, 
        sale_price: Decimal,
        access_token: Optional[str] = None,
        delivery_method: Optional[str] = None,
        prefetched_billing: Optional[Dict[str, Any]] = None,
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
        snapshot = self._resolve_fee_snapshot(
            order=None,
            external_order_id=external_order_id,
            sale_price=sale_price,
            access_token=access_token,
            delivery_method=delivery_method,
            prefetched_billing=prefetched_billing,
        )
        return (snapshot["fees"], snapshot["fee_source"])

    def _get_sale_price(self, order) -> Decimal:
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
                return products_total + delivery
            except Exception:
                return Decimal(str(order.payment_done or 0))
        return Decimal(str(order.payment_done or 0))

    @staticmethod
    def get_manual_order_fees(order) -> Optional[Decimal]:
        """Pobierz sume prowizji z products_json dla zamowien recznych."""
        order_id = str(getattr(order, "order_id", "") or "")
        if not order_id.startswith("manual_"):
            return None

        products_json = getattr(order, "products_json", None)
        if not products_json:
            return Decimal("0")

        try:
            from .shop_shipping import parse_order_products_payload

            products, _meta = parse_order_products_payload(products_json)
        except Exception:
            try:
                products = _json.loads(products_json)
            except Exception:
                return None
            if not isinstance(products, list):
                return None

        total = Decimal("0")
        for product in products:
            if product.get("commission_fee") is not None:
                total += Decimal(str(product["commission_fee"]))
        return total

    def _estimate_fee_snapshot(
        self,
        sale_price: Decimal,
        delivery_method: Optional[str] = None,
        billing_complete: bool = False,
        error: Optional[str] = None,
    ) -> Dict[str, Any]:
        shipping = self._estimate_shipping_cost(delivery_method)
        payment = sale_price * self.DEFAULT_ALLEGRO_FEE_RATE
        fees = payment + shipping
        return {
            "fees": fees,
            "fee_source": "estimated",
            "shipping_estimated": not billing_complete,
            "billing_complete": billing_complete,
            "error": error,
            "payment_fees": payment,
            "shipping_cost": shipping,
        }

    def _resolve_woo_fee_snapshot(
        self,
        sale_price: Decimal,
        order=None,
    ) -> Dict[str, Any]:
        """Opłaty Woo: WooPayments + koszt InPost sprzedawcy."""
        from .order_platform import is_woo_order
        from .shop_shipping import resolve_seller_shipping_cost
        from ..woocommerce_api.payments import get_order_payment_fees

        if order is not None and not is_woo_order(order):
            return self._estimate_fee_snapshot(sale_price)

        payment_method = getattr(order, "payment_method", None) if order else None
        woo_id = getattr(order, "external_order_id", None) if order else None
        if not woo_id and order is not None:
            woo_id = str(getattr(order, "order_id", "") or "").removeprefix("woo_")

        payment = get_order_payment_fees(
            woo_id or "",
            sale_price=sale_price,
            payment_method=payment_method,
        )
        payment_fees = Decimal(str(payment.get("fees") or 0))
        fee_source = payment.get("fee_source") or "estimated"

        shipping = resolve_seller_shipping_cost(order)
        shipping_cost = Decimal(str(shipping["cost"]))
        shipping_estimated = bool(shipping.get("is_estimated", True))

        billing_complete = (fee_source == "api") and (not shipping_estimated)
        return {
            "fees": payment_fees + shipping_cost,
            "fee_source": fee_source if not shipping_estimated else (
                "estimated" if fee_source != "api" else "api"
            ),
            # fee_source for cache: api only when payment is api; shipping flag separate
            "shipping_estimated": shipping_estimated,
            "billing_complete": billing_complete,
            "error": payment.get("error"),
            "payment_fees": payment_fees,
            "shipping_cost": shipping_cost,
            "payment_fee_source": fee_source,
            "shipping_source": shipping.get("source"),
        }

    def _snapshot_from_billing(self, billing: Dict[str, Any]) -> Dict[str, Any]:
        shipping_estimated = bool(billing.get("estimated_shipping"))
        fees_key = "total_fees_with_estimate" if shipping_estimated else "total_fees"
        fees = Decimal(str(billing.get(fees_key) or billing.get("total_fees") or 0))
        return {
            "fees": fees,
            "fee_source": "api",
            "shipping_estimated": shipping_estimated,
            "billing_complete": not shipping_estimated,
            "error": billing.get("error"),
        }

    def _resolve_fee_snapshot(
        self,
        sale_price: Decimal,
        access_token: Optional[str] = None,
        delivery_method: Optional[str] = None,
        prefetched_billing: Optional[Dict[str, Any]] = None,
        order=None,
        external_order_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        billing_started_at = time.perf_counter()
        external_order_id = external_order_id or getattr(order, 'external_order_id', None)

        manual_fees = self.get_manual_order_fees(order)
        if manual_fees is not None:
            return {
                "fees": manual_fees,
                "fee_source": "manual",
                "shipping_estimated": False,
                "billing_complete": True,
                "error": None,
            }

        from .order_platform import is_allegro_order, is_woo_order

        if order is not None and is_woo_order(order):
            return self._resolve_woo_fee_snapshot(sale_price, order)

        cached_fees = _decimal_or_none(
            getattr(order, 'real_profit_allegro_fees', None) if order is not None else None
        )
        cached_is_final = (getattr(order, 'real_profit_is_final', None) is True) if order is not None else False
        if cached_is_final and cached_fees is not None and not access_token and prefetched_billing is None:
            return {
                "fees": cached_fees,
                "fee_source": getattr(order, 'real_profit_fee_source', None) or 'api',
                "shipping_estimated": bool(getattr(order, 'real_profit_shipping_estimated', False)),
                "billing_complete": True,
                "error": getattr(order, 'real_profit_error', None),
            }

        if prefetched_billing and prefetched_billing.get("success"):
            snapshot = self._snapshot_from_billing(prefetched_billing)
            elapsed_ms = (time.perf_counter() - billing_started_at) * 1000
            logger.info(
                "Profit billing prefetched: order_external_id=%s fees=%s entries=%s elapsed_ms=%.1f estimated_shipping=%s",
                external_order_id,
                snapshot["fees"],
                len(prefetched_billing.get("entries") or []),
                elapsed_ms,
                snapshot["shipping_estimated"],
            )
            return snapshot

        # Allegro API tylko dla allegro_* (lub legacy bez prefiksu gdy jest token)
        use_allegro = order is None or is_allegro_order(order)
        if access_token and external_order_id and use_allegro:
            try:
                from ..allegro_api import get_order_billing_summary
                billing = get_order_billing_summary(access_token, external_order_id)
                if billing and billing.get("success") and billing.get("total_fees") is not None:
                    snapshot = self._snapshot_from_billing(billing)
                    elapsed_ms = (time.perf_counter() - billing_started_at) * 1000
                    logger.info(
                        "Profit billing API success: order_external_id=%s fees=%s entries=%s elapsed_ms=%.1f estimated_shipping=%s",
                        external_order_id,
                        snapshot["fees"],
                        len(billing.get("entries") or []),
                        elapsed_ms,
                        snapshot["shipping_estimated"],
                    )
                    return snapshot
                elapsed_ms = (time.perf_counter() - billing_started_at) * 1000
                logger.warning(
                    "Profit billing API fallback: order_external_id=%s reason=empty_or_unsuccessful elapsed_ms=%.1f success=%s error=%s",
                    external_order_id,
                    elapsed_ms,
                    billing.get("success") if isinstance(billing, dict) else None,
                    billing.get("error") if isinstance(billing, dict) else None,
                )
                return self._estimate_fee_snapshot(
                    sale_price,
                    delivery_method,
                    billing_complete=not bool(external_order_id),
                    error=billing.get("error") if isinstance(billing, dict) else None,
                )
            except Exception as exc:
                elapsed_ms = (time.perf_counter() - billing_started_at) * 1000
                logger.warning(
                    "Profit billing API exception: order_external_id=%s elapsed_ms=%.1f error=%s",
                    external_order_id,
                    elapsed_ms,
                    exc,
                )
                return self._estimate_fee_snapshot(
                    sale_price,
                    delivery_method,
                    billing_complete=not bool(external_order_id),
                    error=str(exc),
                )

        if use_allegro:
            return self._estimate_fee_snapshot(
                sale_price,
                delivery_method,
                billing_complete=not bool(external_order_id),
            )

        # Nieznana platforma (nie Allegro/Woo/manual) — bez sztucznej prowizji Allegro
        return {
            "fees": Decimal("0"),
            "fee_source": "estimated",
            "shipping_estimated": False,
            "billing_complete": True,
            "error": None,
        }

    def _build_profit_breakdown(
        self,
        order,
        sale_price: Decimal,
        fee_snapshot: Dict[str, Any],
        trace_label: Optional[str] = None,
        started_at: Optional[float] = None,
    ) -> ProfitBreakdown:
        purchase_cost = self.get_purchase_cost_for_order(order.order_id)
        packaging_cost = self.get_packaging_cost()
        profit = sale_price - fee_snapshot["fees"] - purchase_cost - packaging_cost

        elapsed_ms = ((time.perf_counter() - started_at) * 1000) if started_at else 0
        order_id = getattr(order, 'order_id', None)
        logger.info(
            "Profit order calculated: trace=%s order_id=%s external_order_id=%s sale_price=%s fees=%s fee_source=%s purchase_cost=%s packaging_cost=%s profit=%s billing_complete=%s elapsed_ms=%.1f",
            trace_label or '-',
            order_id,
            getattr(order, 'external_order_id', None),
            sale_price,
            fee_snapshot["fees"],
            fee_snapshot["fee_source"],
            purchase_cost,
            packaging_cost,
            profit,
            fee_snapshot["billing_complete"],
            elapsed_ms,
        )

        return ProfitBreakdown(
            order_id=order.order_id,
            sale_price=sale_price,
            allegro_fees=fee_snapshot["fees"],
            purchase_cost=purchase_cost,
            packaging_cost=packaging_cost,
            profit=profit,
            fee_source=fee_snapshot["fee_source"],
            billing_complete=fee_snapshot["billing_complete"],
            shipping_estimated=fee_snapshot["shipping_estimated"],
        )

    def get_cached_order_profit(self, order) -> Optional[ProfitBreakdown]:
        cached_fields = [
            getattr(order, 'real_profit_sale_price', None),
            getattr(order, 'real_profit_purchase_cost', None),
            getattr(order, 'real_profit_packaging_cost', None),
            getattr(order, 'real_profit_allegro_fees', None),
            getattr(order, 'real_profit_amount', None),
        ]
        if any(value is None for value in cached_fields):
            return None

        return ProfitBreakdown(
            order_id=order.order_id,
            sale_price=Decimal(str(order.real_profit_sale_price)),
            allegro_fees=Decimal(str(order.real_profit_allegro_fees)),
            purchase_cost=Decimal(str(order.real_profit_purchase_cost)),
            packaging_cost=Decimal(str(order.real_profit_packaging_cost)),
            profit=Decimal(str(order.real_profit_amount)),
            fee_source=getattr(order, 'real_profit_fee_source', None) or 'estimated',
            billing_complete=bool(getattr(order, 'real_profit_is_final', False)),
            shipping_estimated=bool(getattr(order, 'real_profit_shipping_estimated', False)),
        )

    def refresh_order_profit_cache(
        self,
        order,
        access_token: Optional[str] = None,
        trace_label: Optional[str] = None,
        prefetched_billing: Optional[Dict[str, Any]] = None,
    ) -> ProfitBreakdown:
        sale_price = self._get_sale_price(order)
        fee_snapshot = self._resolve_fee_snapshot(
            sale_price=sale_price,
            access_token=access_token,
            delivery_method=getattr(order, 'delivery_method', None),
            prefetched_billing=prefetched_billing,
            order=order,
        )
        breakdown = self._build_profit_breakdown(
            order,
            sale_price,
            fee_snapshot,
            trace_label=trace_label,
            started_at=time.perf_counter(),
        )

        order.real_profit_sale_price = breakdown.sale_price
        order.real_profit_purchase_cost = breakdown.purchase_cost
        order.real_profit_packaging_cost = breakdown.packaging_cost
        order.real_profit_allegro_fees = breakdown.allegro_fees
        order.real_profit_amount = breakdown.profit
        order.real_profit_fee_source = breakdown.fee_source
        order.real_profit_shipping_estimated = breakdown.shipping_estimated
        order.real_profit_is_final = breakdown.billing_complete
        order.real_profit_error = fee_snapshot.get("error")
        order.real_profit_updated_at = datetime.now(timezone.utc)
        return breakdown
    
    def _estimate_shipping_cost(self, delivery_method: Optional[str] = None) -> Decimal:
        """Szacuje koszt wysylki Allegro Smart (tylko ścieżka Allegro)."""
        if not delivery_method:
            return self.DEFAULT_SHIPPING_COST

        try:
            from ..allegro_api.shipping import estimate_allegro_shipping_cost

            estimate = estimate_allegro_shipping_cost(delivery_method, Decimal("0"))
            if isinstance(estimate, dict):
                cost = estimate.get("estimated_cost")
                if cost is not None:
                    return Decimal(str(cost))
            if isinstance(estimate, (int, float, Decimal, str)):
                return Decimal(str(estimate))
        except Exception:
            pass
        return self.DEFAULT_SHIPPING_COST

    def calculate_order_profit(
        self,
        order,
        access_token: Optional[str] = None,
        trace_label: Optional[str] = None,
        prefetched_billing: Optional[Dict[str, Any]] = None,
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
        sale_price = self._get_sale_price(order)
        fee_snapshot = self._resolve_fee_snapshot(
            sale_price=sale_price,
            access_token=access_token,
            delivery_method=getattr(order, "delivery_method", None),
            prefetched_billing=prefetched_billing,
            order=order,
        )
        return self._build_profit_breakdown(
            order,
            sale_price,
            fee_snapshot,
            trace_label=trace_label,
            started_at=order_started_at,
        )

    def _prefetch_order_billing_summaries(
        self,
        orders: List[Any],
        access_token: Optional[str],
        trace_label: Optional[str] = None,
    ) -> Dict[str, Dict[str, Any]]:
        if not access_token:
            return {}

        order_ids = []
        for order in orders:
            external_order_id = getattr(order, 'external_order_id', None)
            if external_order_id:
                order_ids.append(external_order_id)

        if len(order_ids) < 2:
            return {}

        from ..allegro_api import get_order_billing_summary

        max_workers = min(8, len(order_ids))
        started_at = time.perf_counter()
        summaries: Dict[str, Dict[str, Any]] = {}
        failed = 0

        logger.info(
            "Profit billing prefetch start: trace=%s orders=%s workers=%s",
            trace_label or '-',
            len(order_ids),
            max_workers,
        )

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_order_id = {
                executor.submit(get_order_billing_summary, access_token, order_id): order_id
                for order_id in order_ids
            }
            for future in as_completed(future_to_order_id):
                order_id = future_to_order_id[future]
                try:
                    summaries[order_id] = future.result()
                except Exception as exc:
                    failed += 1
                    logger.warning(
                        "Profit billing prefetch failed: trace=%s order_external_id=%s error=%s",
                        trace_label or '-',
                        order_id,
                        exc,
                    )

        elapsed_ms = (time.perf_counter() - started_at) * 1000
        logger.info(
            "Profit billing prefetch done: trace=%s requested=%s loaded=%s failed=%s elapsed_ms=%.1f",
            trace_label or '-',
            len(order_ids),
            len(summaries),
            failed,
            elapsed_ms,
        )
        return summaries
    
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
        from ..models.orders import Order, OrderProduct
        from ..models.returns import Return
        from ..models.settings import FixedCost
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
                Order.payment_method_cod.is_(True),
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
                Order.payment_method_cod.is_(True),
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
        total_packaging_cost = Decimal("0")
        cache_hits = 0
        cache_misses = 0
        incomplete_orders = 0
        api_fee_orders = 0
        estimated_fee_orders = 0
        loop_started_at = time.perf_counter()
        
        for order in orders:
            breakdown = self.get_cached_order_profit(order)
            if breakdown is None:
                cache_misses += 1
                breakdown = self.calculate_order_profit(
                    order,
                    access_token=None,
                    trace_label=trace_label,
                )
            else:
                cache_hits += 1
            total_revenue += breakdown.sale_price
            total_purchase_cost += breakdown.purchase_cost
            total_allegro_fees += breakdown.allegro_fees
            total_packaging_cost += breakdown.packaging_cost
            if breakdown.fee_source == 'api':
                api_fee_orders += 1
            else:
                estimated_fee_orders += 1
            if not breakdown.billing_complete:
                incomplete_orders += 1
        loop_elapsed_ms = (time.perf_counter() - loop_started_at) * 1000

        if loop_elapsed_ms > 5000:
            logger.warning(
                "Profit period summary slow loop: trace=%s orders=%s cache_hits=%s cache_misses=%s incomplete_orders=%s api_fee_orders=%s estimated_fee_orders=%s elapsed_ms=%.1f",
                trace_label or '-',
                len(orders),
                cache_hits,
                cache_misses,
                incomplete_orders,
                api_fee_orders,
                estimated_fee_orders,
                loop_elapsed_ms,
            )
        else:
            logger.info(
                "Profit period summary loop done: trace=%s orders=%s cache_hits=%s cache_misses=%s incomplete_orders=%s api_fee_orders=%s estimated_fee_orders=%s elapsed_ms=%.1f",
                trace_label or '-',
                len(orders),
                cache_hits,
                cache_misses,
                incomplete_orders,
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
            fc_query = self.db.query(FixedCost).filter(FixedCost.is_active.is_(True)).all()
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
