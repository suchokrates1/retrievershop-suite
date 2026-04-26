"""Wspolny kontekst zaleznosci dla modulow endpointow stats API."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import logging
import time

from flask import jsonify, request
from sqlalchemy import case, func, or_

from ..db import get_session
from ..models import (
    AllegroBillingType,
    AllegroOffer,
    AllegroPriceHistory,
    Message,
    Order,
    OrderProduct,
    OrderStatusLog,
    PriceReportItem,
    Return,
    ReturnStatusLog,
    Thread,
)
from ..domain.financial import FinancialCalculator as _DefaultFinancialCalculator
from ..services.billing_types import (
    BILLING_CATEGORY_CHOICES,
    _upsert_billing_types,
    sync_billing_types_dictionary,
)
from ..services.stats_runtime import (
    TELEMETRY as _TELEMETRY,
    cache_get as _cache_get,
    cache_set as _cache_set,
    endpoint_name as _endpoint_name,
    record_telemetry as _record_telemetry,
    telemetry_stats as _telemetry_stats,
)
from ..services.stats_logistics import (
    build_alerts as _build_alerts,
    carrier_label as _carrier_label,
    delivery_method_label as _delivery_method_label,
    group_logistics_rows as _group_logistics_rows,
)
from ..services.stats_orders import (
    bucket_key as _bucket_key,
    fetch_orders as _fetch_orders,
    is_cod as _is_cod,
    order_products_map as _order_products_map,
    order_revenue as _order_revenue,
)
from ..services.stats_support import (
    build_cache_key as _build_cache_key,
    export_table as _export_table,
    format_filters as _format_filters,
    json_error as _json_error,
    parse_filters as _parse_filters,
    pct_change as _pct_change,
    period_offsets as _period_offsets,
    to_ts as _to_ts,
)
from ..settings_store import settings_store

logger = logging.getLogger("magazyn.stats")


def FinancialCalculator(*args, **kwargs):
    try:
        from .. import stats as stats_module
        calculator_cls = getattr(stats_module, "FinancialCalculator", _DefaultFinancialCalculator)
    except Exception:
        calculator_cls = _DefaultFinancialCalculator
    if calculator_cls is FinancialCalculator:
        calculator_cls = _DefaultFinancialCalculator
    return calculator_cls(*args, **kwargs)


__all__ = [
    "AllegroBillingType",
    "AllegroOffer",
    "AllegroPriceHistory",
    "BILLING_CATEGORY_CHOICES",
    "Decimal",
    "FinancialCalculator",
    "Message",
    "Order",
    "OrderProduct",
    "OrderStatusLog",
    "PriceReportItem",
    "Return",
    "ReturnStatusLog",
    "Thread",
    "_TELEMETRY",
    "_build_alerts",
    "_build_cache_key",
    "_bucket_key",
    "_cache_get",
    "_cache_set",
    "_carrier_label",
    "_delivery_method_label",
    "_endpoint_name",
    "_export_table",
    "_fetch_orders",
    "_format_filters",
    "_group_logistics_rows",
    "_is_cod",
    "_json_error",
    "_order_products_map",
    "_order_revenue",
    "_parse_filters",
    "_period_offsets",
    "_pct_change",
    "_record_telemetry",
    "_telemetry_stats",
    "_to_ts",
    "_upsert_billing_types",
    "case",
    "datetime",
    "defaultdict",
    "func",
    "get_session",
    "json",
    "jsonify",
    "logger",
    "logging",
    "or_",
    "request",
    "settings_store",
    "sync_billing_types_dictionary",
    "time",
    "timedelta",
    "timezone",
]
