"""Router API statystyk.

Implementacje endpointow sa podzielone w modulach `magazyn.services.stats_api_*`.
Ten modul zachowuje URL-e i prywatne aliasy kompatybilnosciowe uzywane przez testy.
"""

from __future__ import annotations

from flask import Blueprint

from .auth import login_required
from .domain.financial import FinancialCalculator as FinancialCalculator
from .services.billing_types import _default_billing_mapping_category  # noqa: F401 - publiczny helper kompatybilnosci
from .services.stats_runtime import (
    FAST_CACHE as _FAST_CACHE,  # noqa: F401 - publiczny cache kompatybilnosci testow
    FAST_CACHE_TTL_SECONDS as _FAST_CACHE_TTL_SECONDS,  # noqa: F401 - publiczny TTL kompatybilnosci
    TELEMETRY as _TELEMETRY,
)
from .services.stats_logistics import (
    build_alerts as _build_alerts,
    carrier_label as _carrier_label,
    delivery_method_label as _delivery_method_label,
    group_logistics_rows as _group_logistics_rows,
)
from .services.stats_orders import (
    bucket_key as _bucket_key,
    fetch_orders as _fetch_orders,
    filter_orders_by_payment as _filter_orders_by_payment,  # noqa: F401 - publiczny helper kompatybilnosci
    is_cod as _is_cod,
    order_products_map as _order_products_map,
    order_revenue as _order_revenue,
)
from .services.stats_support import (
    StatsFilters,  # noqa: F401 - publiczny typ kompatybilnosci testow
    build_cache_key as _build_cache_key,
    export_table as _export_table,
    format_filters as _format_filters,
    json_error as _json_error,
    parse_date as _parse_date,  # noqa: F401 - publiczny helper kompatybilnosci
    parse_filters as _parse_filters,
    pct_change as _pct_change,
    period_offsets as _period_offsets,
    to_ts as _to_ts,
)
from .settings_store import settings_store
from .services import stats_api_financial as _financial_endpoints
from .services import stats_api_returns as _returns_endpoints
from .services import stats_api_billing as _billing_endpoints
from .services import stats_api_logistics as _logistics_endpoints
from .services import stats_api_catalog as _catalog_endpoints
from .services import stats_api_support as _support_endpoints


__all__ = [
    "FinancialCalculator",
    "StatsFilters",
    "_FAST_CACHE",
    "_FAST_CACHE_TTL_SECONDS",
    "_TELEMETRY",
    "_build_alerts",
    "_build_cache_key",
    "_bucket_key",
    "_carrier_label",
    "_default_billing_mapping_category",
    "_delivery_method_label",
    "_export_table",
    "_fetch_orders",
    "_filter_orders_by_payment",
    "_format_filters",
    "_group_logistics_rows",
    "_is_cod",
    "_json_error",
    "_order_products_map",
    "_order_revenue",
    "_parse_date",
    "_parse_filters",
    "_pct_change",
    "_period_offsets",
    "_to_ts",
    "settings_store",
]


bp = Blueprint("stats", __name__, url_prefix="/api/stats")


@bp.route("/overview")
@login_required
def stats_overview():
    return _financial_endpoints.stats_overview()


@bp.route("/sales")
@login_required
def stats_sales():
    return _financial_endpoints.stats_sales()


@bp.route("/profit")
@login_required
def stats_profit():
    return _financial_endpoints.stats_profit()


@bp.route("/allegro-costs")
@login_required
def stats_allegro_costs():
    return _financial_endpoints.stats_allegro_costs()


@bp.route("/ads-offer-analytics")
@login_required
def stats_ads_offer_analytics():
    return _financial_endpoints.stats_ads_offer_analytics()


@bp.route("/refund-timeline")
@login_required
def stats_refund_timeline():
    return _returns_endpoints.stats_refund_timeline()


@bp.route("/returns")
@login_required
def stats_returns():
    return _returns_endpoints.stats_returns()


@bp.route("/billing-types", methods=["GET"])
@login_required
def stats_billing_types_list():
    return _billing_endpoints.stats_billing_types_list()


@bp.route("/billing-types/<string:type_id>", methods=["PUT"])
@login_required
def stats_billing_type_update(type_id: str):
    return _billing_endpoints.stats_billing_type_update(type_id)


@bp.route("/billing-types/sync", methods=["POST"])
@login_required
def stats_billing_types_sync():
    return _billing_endpoints.stats_billing_types_sync()


@bp.route("/logistics")
@login_required
def stats_logistics():
    return _logistics_endpoints.stats_logistics()


@bp.route("/products")
@login_required
def stats_products():
    return _catalog_endpoints.stats_products()


@bp.route("/competition")
@login_required
def stats_competition():
    return _catalog_endpoints.stats_competition()


@bp.route("/offer-publication-history")
@login_required
def stats_offer_publication_history():
    return _catalog_endpoints.stats_offer_publication_history()


@bp.route("/telemetry")
@login_required
def stats_telemetry():
    return _support_endpoints.stats_telemetry()


@bp.route("/order-funnel")
@login_required
def stats_order_funnel():
    return _logistics_endpoints.stats_order_funnel()


@bp.route("/shipment-errors")
@login_required
def stats_shipment_errors():
    return _logistics_endpoints.stats_shipment_errors()


@bp.route("/customer-support")
@login_required
def stats_customer_support():
    return _support_endpoints.stats_customer_support()


@bp.route("/invoice-coverage")
@login_required
def stats_invoice_coverage():
    return _support_endpoints.stats_invoice_coverage()
