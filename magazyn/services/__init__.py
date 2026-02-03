"""
Pakiet serwisow biznesowych.

Zawiera logike biznesowa wyodrebniona z kontrolerow Flask.
"""

from .price_checker import PriceCheckerService, DebugContext, build_price_checks
from .order_detail_builder import (
    OrderDetailBuilder,
    build_order_detail_context,
    SHIPPING_STAGES,
    RETURN_STAGES,
)
from .return_sync import ReturnSyncService, create_return_sync_service
from .allegro_promotions import (
    PromoOption,
    PromoSummary,
    get_promotions_summary,
    check_and_notify_promotions,
    disable_promotion,
)

# Re-export z domain dla kompatybilnosci wstecznej
from ..domain.inventory import consume_order_stock
from ..domain.reports import get_sales_summary

__all__ = [
    "PriceCheckerService",
    "DebugContext",
    "build_price_checks",
    "OrderDetailBuilder",
    "build_order_detail_context",
    "SHIPPING_STAGES",
    "RETURN_STAGES",
    "ReturnSyncService",
    "create_return_sync_service",
    # Allegro promotions
    "PromoOption",
    "PromoSummary",
    "get_promotions_summary",
    "check_and_notify_promotions",
    "disable_promotion",
    # Kompatybilnosc wsteczna
    "consume_order_stock",
    "get_sales_summary",
]
