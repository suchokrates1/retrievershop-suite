"""API statystyk (MVP v1)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import time
from collections import defaultdict
import io
import csv

import pandas as pd
from flask import Blueprint, jsonify, request, Response
from sqlalchemy import case, func, or_

from .auth import login_required
from .db import get_session
from .models import (
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
from .domain.financial import FinancialCalculator
from .settings_store import settings_store


bp = Blueprint("stats", __name__, url_prefix="/api/stats")

_FAST_CACHE: dict[str, tuple[float, dict]] = {}
_FAST_CACHE_TTL_SECONDS = 60
_TELEMETRY: dict[str, dict[str, float]] = defaultdict(
    lambda: {
        "requests": 0,
        "cache_hits": 0,
        "cache_misses": 0,
        "total_response_ms": 0.0,
    }
)

BILLING_CATEGORY_CHOICES = {
    "commission_organic",
    "commission_promoted",
    "shipping",
    "promo",
    "ads",
    "listing",
    "refund",
    "bonus",
    "other",
}


def _default_billing_mapping_category(type_id: str) -> str:
    from .allegro_api.billing import (
        ORGANIC_COMMISSION_TYPES,
        PROMOTED_COMMISSION_TYPES,
        SHIPPING_TYPES,
        PROMO_TYPES,
        LISTING_TYPES,
        REFUND_TYPES,
        CAMPAIGN_BONUS_TYPES,
    )

    if type_id in ORGANIC_COMMISSION_TYPES:
        return "commission_organic"
    if type_id in PROMOTED_COMMISSION_TYPES:
        return "commission_promoted"
    if type_id in SHIPPING_TYPES:
        return "shipping"
    if type_id in PROMO_TYPES:
        if type_id in {"NSP", "ADS"}:
            return "ads"
        return "promo"
    if type_id in LISTING_TYPES:
        return "listing"
    if type_id in REFUND_TYPES:
        return "refund"
    if type_id in CAMPAIGN_BONUS_TYPES:
        return "bonus"
    return "other"


@dataclass
class StatsFilters:
    date_from: datetime
    date_to: datetime
    granularity: str
    platform: str
    payment_type: str


def _json_error(code: str, message: str, status: int = 400):
    return (
        jsonify(
            {
                "ok": False,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "data": None,
                "errors": [{"code": code, "message": message}],
            }
        ),
        status,
    )


def _parse_date(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except Exception:
        return None


def _parse_filters() -> tuple[StatsFilters | None, tuple | None]:
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    default_from = today.replace(day=1)
    default_to = today + timedelta(days=1)

    date_from_raw = (request.args.get("date_from") or "").strip()
    date_to_raw = (request.args.get("date_to") or "").strip()
    granularity = (request.args.get("granularity") or "day").strip().lower()
    platform = (request.args.get("platform") or "all").strip().lower()
    payment_type = (request.args.get("payment_type") or "all").strip().lower()

    if granularity not in {"day", "week", "month"}:
        return None, _json_error(
            "INVALID_GRANULARITY", "Dozwolone granularity: day, week, month"
        )

    if platform not in {"all", "allegro", "shop", "ebay", "manual"}:
        return None, _json_error(
            "INVALID_PLATFORM", "Dozwolone platform: all, allegro, shop, ebay, manual"
        )

    if payment_type not in {"all", "cod", "online"}:
        return None, _json_error(
            "INVALID_PAYMENT_TYPE", "Dozwolone payment_type: all, cod, online"
        )

    if date_from_raw:
        date_from = _parse_date(date_from_raw)
        if not date_from:
            return None, _json_error("INVALID_DATE_FROM", "date_from musi miec format YYYY-MM-DD")
    else:
        date_from = default_from

    if date_to_raw:
        date_to = _parse_date(date_to_raw)
        if not date_to:
            return None, _json_error("INVALID_DATE_TO", "date_to musi miec format YYYY-MM-DD")
        # date_to jest inkluzywne na poziomie dnia
        date_to = date_to + timedelta(days=1)
    else:
        date_to = default_to

    if date_from >= date_to:
        return None, _json_error("INVALID_DATE_RANGE", "date_from musi byc mniejsze niz date_to")

    return StatsFilters(
        date_from=date_from,
        date_to=date_to,
        granularity=granularity,
        platform=platform,
        payment_type=payment_type,
    ), None


def _is_cod(order: Order) -> bool:
    method = (order.payment_method or "").lower()
    return bool(order.payment_method_cod) or ("pobranie" in method)


def _build_cache_key(filters: StatsFilters) -> str:
    return "|".join(
        [
            filters.date_from.strftime("%Y-%m-%d"),
            filters.date_to.strftime("%Y-%m-%d"),
            filters.granularity,
            filters.platform,
            filters.payment_type,
        ]
    )


def _cache_get(key: str) -> dict | None:
    item = _FAST_CACHE.get(key)
    if not item:
        return None
    expires_at, payload = item
    if time.time() > expires_at:
        _FAST_CACHE.pop(key, None)
        return None
    return payload


def _cache_set(key: str, payload: dict) -> None:
    _FAST_CACHE[key] = (time.time() + _FAST_CACHE_TTL_SECONDS, payload)


def _to_ts(dt: datetime) -> int:
    return int(dt.timestamp())


def _pct_change(current: Decimal, previous: Decimal) -> float | None:
    if previous == 0:
        return None
    return float(((current - previous) / previous) * 100)


def _order_products_map(db, order_ids: list[str]) -> dict[str, dict[str, Decimal | int]]:
    if not order_ids:
        return {}

    rows = (
        db.query(
            OrderProduct.order_id,
            func.sum(OrderProduct.quantity).label("qty"),
            func.sum(OrderProduct.price_brutto * OrderProduct.quantity).label("gross"),
        )
        .filter(OrderProduct.order_id.in_(order_ids))
        .group_by(OrderProduct.order_id)
        .all()
    )
    return {
        row.order_id: {
            "qty": int(row.qty or 0),
            "gross": Decimal(str(row.gross or 0)),
        }
        for row in rows
    }


def _order_revenue(order: Order, products_map: dict[str, dict[str, Decimal | int]]) -> Decimal:
    order_products = products_map.get(order.order_id, {"gross": Decimal("0")})
    gross = Decimal(str(order_products.get("gross", Decimal("0"))))
    if _is_cod(order):
        return gross + Decimal(str(order.delivery_price or 0))
    return Decimal(str(order.payment_done or 0))


def _filter_orders_by_payment(orders: list[Order], payment_type: str) -> list[Order]:
    if payment_type == "all":
        return orders
    if payment_type == "cod":
        return [o for o in orders if _is_cod(o)]
    return [o for o in orders if not _is_cod(o)]


def _fetch_orders(db, filters: StatsFilters, start_ts: int, end_ts: int) -> list[Order]:
    q = db.query(Order).filter(Order.date_add >= start_ts, Order.date_add < end_ts)
    if filters.platform != "all":
        q = q.filter(Order.platform == filters.platform)
    orders = q.all()
    return _filter_orders_by_payment(orders, filters.payment_type)


def _bucket_key(ts: int, granularity: str) -> str:
    dt = datetime.fromtimestamp(ts)
    if granularity == "week":
        week_start = dt - timedelta(days=dt.weekday())
        return week_start.strftime("%Y-%m-%d")
    if granularity == "month":
        return dt.strftime("%Y-%m")
    return dt.strftime("%Y-%m-%d")


def _period_offsets(filters: StatsFilters) -> tuple[int, int, int, int]:
    current_start = _to_ts(filters.date_from)
    current_end = _to_ts(filters.date_to)
    period_len = filters.date_to - filters.date_from
    prev_start = _to_ts(filters.date_from - period_len)
    prev_end = current_start
    return current_start, current_end, prev_start, prev_end


def _upsert_billing_types(db, billing_types: list[dict]) -> dict[str, str]:
    """Synchronizuje slownik billing types do bazy i zwraca mapowanie id->nazwa."""
    now = datetime.now(timezone.utc)
    existing = {row.type_id: row for row in db.query(AllegroBillingType).all()}

    for item in billing_types:
        type_id = (item.get("id") or "").strip()
        if not type_id:
            continue

        name = (item.get("description") or item.get("name") or type_id).strip()
        description = (item.get("description") or item.get("name") or "").strip() or None

        inferred_category = _default_billing_mapping_category(type_id)
        row = existing.get(type_id)
        if row is None:
            row = AllegroBillingType(
                type_id=type_id,
                name=name,
                description=description,
                mapping_category=inferred_category,
                mapping_version=1,
                last_seen_at=now,
            )
            db.add(row)
            existing[type_id] = row
        else:
            row.name = name
            row.description = description
            if not row.mapping_category:
                row.mapping_category = inferred_category
            row.last_seen_at = now

    db.flush()
    return {row.type_id: (row.name or row.type_id) for row in existing.values()}


def _build_alerts(*, returns_rate: float | None = None, refund_rate: float | None = None, lead_time_hours: float | None = None) -> list[dict]:
    alerts: list[dict] = []
    if returns_rate is not None and returns_rate > 8.0:
        alerts.append(
            {
                "code": "RETURNS_RATE_HIGH",
                "level": "warning",
                "message": "Wskaznik zwrotow przekracza prog 8%",
                "value": returns_rate,
                "threshold": 8.0,
            }
        )
    if refund_rate is not None and refund_rate < 80.0:
        alerts.append(
            {
                "code": "REFUND_RATE_LOW",
                "level": "warning",
                "message": "Skutecznosc refundow jest ponizej progu 80%",
                "value": refund_rate,
                "threshold": 80.0,
            }
        )
    if lead_time_hours is not None and lead_time_hours > 48.0:
        alerts.append(
            {
                "code": "LEAD_TIME_HIGH",
                "level": "critical",
                "message": "Sredni lead time przekracza 48h",
                "value": lead_time_hours,
                "threshold": 48.0,
            }
        )
    return alerts


def _carrier_label(order: Order) -> str:
    raw_values = [
        (order.courier_code or "").strip(),
        (order.delivery_package_module or "").strip(),
        (order.delivery_method or "").strip(),
    ]
    combined = " ".join(value.lower() for value in raw_values if value)
    if "inpost" in combined or "paczkomat" in combined:
        return "InPost"
    if "dpd" in combined:
        return "DPD"
    if "dhl" in combined:
        return "DHL"
    if "poczta" in combined or "pocztex" in combined:
        return "Poczta Polska"
    if "gls" in combined:
        return "GLS"
    if "ups" in combined:
        return "UPS"
    if "fedex" in combined:
        return "FedEx"
    if "orlen" in combined:
        return "Orlen"
    if "allegro" in combined and "one" in combined:
        return "Allegro One"

    for value in raw_values:
        if value:
            return value
    return "Nieznany"


def _delivery_method_label(order: Order) -> str:
    return (
        (order.delivery_method or "").strip()
        or (order.delivery_package_module or "").strip()
        or _carrier_label(order)
    )


def _group_logistics_rows(rows: dict[str, dict[str, object]]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for row in rows.values():
        lead_times = [float(value) for value in row.pop("lead_times", [])]
        delivered_total = int(row.get("delivered_total", 0) or 0)
        on_time_rate = (
            sum(1 for value in lead_times if value <= 48.0) / delivered_total * 100
            if delivered_total
            else 0.0
        )
        avg_lead = sum(lead_times) / len(lead_times) if lead_times else 0.0
        result.append(
            {
                **row,
                "avg_lead_time_hours": round(avg_lead, 2),
                "on_time_rate_48h": round(on_time_rate, 2),
            }
        )

    result.sort(
        key=lambda item: (
            -int(item.get("shipped_total", 0) or 0),
            float(item.get("avg_lead_time_hours", 0.0) or 0.0),
            str(item.get("carrier", item.get("delivery_method", ""))),
        )
    )
    return result


def _format_filters(filters: StatsFilters) -> dict[str, str]:
    return {
        "date_from": filters.date_from.strftime("%Y-%m-%d"),
        "date_to": (filters.date_to - timedelta(days=1)).strftime("%Y-%m-%d"),
        "granularity": filters.granularity,
        "platform": filters.platform,
        "payment_type": filters.payment_type,
    }


def sync_billing_types_dictionary(access_token: str) -> dict[str, int]:
    """Synchronizuje slownik billing types z Allegro do bazy danych."""
    from .allegro_api import fetch_billing_types

    types_data = fetch_billing_types(access_token)
    if isinstance(types_data, dict):
        types_list = types_data.get("billingTypes", [])
    else:
        types_list = types_data or []

    with get_session() as db:
        before = db.query(AllegroBillingType).count()
        _upsert_billing_types(db, types_list)
        after = db.query(AllegroBillingType).count()

    return {
        "fetched": len(types_list),
        "known": after,
        "created": max(after - before, 0),
    }


def _export_table(rows: list[dict], filename_prefix: str, export_format: str) -> Response:
    if export_format == "csv":
        output = io.StringIO()
        fieldnames = list(rows[0].keys()) if rows else ["empty"]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
        content = output.getvalue()
        return Response(
            content,
            mimetype="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename={filename_prefix}.csv",
            },
        )

    if export_format == "xlsx":
        df = pd.DataFrame(rows or [{"empty": "no-data"}])
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="stats")
        buffer.seek(0)
        return Response(
            buffer.read(),
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f"attachment; filename={filename_prefix}.xlsx",
            },
        )

    return _json_error("INVALID_EXPORT_FORMAT", "Dozwolone formaty eksportu: csv, xlsx")


def _endpoint_name(cache_key: str) -> str:
    return cache_key.split("|", 1)[0] if "|" in cache_key else "overview"


def _record_telemetry(endpoint: str, cache_state: str, started_at: float) -> float:
    elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
    entry = _TELEMETRY[endpoint]
    entry["requests"] += 1
    entry["total_response_ms"] += elapsed_ms
    if cache_state == "hit":
        entry["cache_hits"] += 1
    else:
        entry["cache_misses"] += 1
    return elapsed_ms


def _telemetry_stats(endpoint: str, response_ms: float) -> dict[str, float]:
    entry = _TELEMETRY[endpoint]
    requests_total = entry["requests"] or 1
    cache_ratio = (entry["cache_hits"] / requests_total) * 100
    avg_response = entry["total_response_ms"] / requests_total
    return {
        "response_ms": response_ms,
        "avg_response_ms": round(avg_response, 2),
        "cache_hit_ratio": round(cache_ratio, 2),
    }


@bp.route("/overview")
@login_required
def stats_overview():
    started_at = time.perf_counter()
    filters, err = _parse_filters()
    if err:
        return err

    cache_key = "overview|" + _build_cache_key(filters)
    cached_payload = _cache_get(cache_key)
    if cached_payload is not None:
        endpoint = _endpoint_name(cache_key)
        response_ms = _record_telemetry(endpoint, "hit", started_at)
        cached = dict(cached_payload)
        cached["generated_at"] = datetime.now(timezone.utc).isoformat()
        cached["meta"] = dict(cached.get("meta") or {})
        cached["meta"]["cache"] = "hit"
        cached["meta"]["telemetry"] = _telemetry_stats(endpoint, response_ms)
        return jsonify(cached)

    cs, ce, ps, pe = _period_offsets(filters)
    wow_end = ce
    wow_start = ce - 7 * 86400
    wow_prev_end = wow_start
    wow_prev_start = wow_start - 7 * 86400

    def _agg(start_ts: int, end_ts: int) -> dict:
        with get_session() as db:
            orders = _fetch_orders(db, filters, start_ts, end_ts)
            order_ids = [o.order_id for o in orders]
            products_map = _order_products_map(db, order_ids)

            revenue_gross = Decimal("0")
            items_sold = 0
            cod_orders = 0

            for order in orders:
                if _is_cod(order):
                    cod_orders += 1
                p = products_map.get(order.order_id, {"qty": 0, "gross": Decimal("0")})
                items_sold += int(p["qty"])
                revenue_gross += _order_revenue(order, products_map)

            orders_count = len(orders)
            aov = (revenue_gross / orders_count) if orders_count else Decimal("0")

            active_returns = 0
            if order_ids:
                active_returns = (
                    db.query(Return)
                    .filter(Return.order_id.in_(order_ids), Return.status != "cancelled")
                    .count()
                )
            returns_rate = (Decimal(str(active_returns)) / Decimal(str(orders_count)) * 100) if orders_count else Decimal("0")
            cod_share = (Decimal(str(cod_orders)) / Decimal(str(orders_count)) * 100) if orders_count else Decimal("0")

        return {
            "revenue_gross": revenue_gross,
            "orders_count": Decimal(str(orders_count)),
            "items_sold": Decimal(str(items_sold)),
            "aov": aov,
            "returns_rate": returns_rate,
            "cod_share": cod_share,
        }

    cur = _agg(cs, ce)
    prv = _agg(ps, pe)
    wow_cur = _agg(wow_start, wow_end)
    wow_prv = _agg(wow_prev_start, wow_prev_end)

    def _kpi(key: str) -> dict:
        return {
            "value": float(cur[key]),
            "mom": _pct_change(cur[key], prv[key]),
            "wow": _pct_change(wow_cur[key], wow_prv[key]),
        }

    payload = {
        "ok": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "filters": {
            "date_from": filters.date_from.strftime("%Y-%m-%d"),
            "date_to": (filters.date_to - timedelta(days=1)).strftime("%Y-%m-%d"),
            "granularity": filters.granularity,
            "platform": filters.platform,
            "payment_type": filters.payment_type,
        },
        "data": {
            "kpi": {
                "revenue_gross": _kpi("revenue_gross"),
                "orders_count": _kpi("orders_count"),
                "items_sold": _kpi("items_sold"),
                "aov": _kpi("aov"),
                "returns_rate": _kpi("returns_rate"),
                "cod_share": _kpi("cod_share"),
            }
        },
        "meta": {
            "confidence": "medium",
            "sources": ["db.orders", "db.order_products", "db.returns"],
            "cache": "miss",
            "telemetry": {},
        },
        "errors": [],
    }
    endpoint = _endpoint_name(cache_key)
    response_ms = _record_telemetry(endpoint, "miss", started_at)
    payload["meta"]["telemetry"] = _telemetry_stats(endpoint, response_ms)
    _cache_set(cache_key, payload)
    return jsonify(payload)


@bp.route("/sales")
@login_required
def stats_sales():
    started_at = time.perf_counter()
    filters, err = _parse_filters()
    if err:
        return err

    cache_key = "sales|" + _build_cache_key(filters)
    cached_payload = _cache_get(cache_key)
    if cached_payload is not None:
        endpoint = _endpoint_name(cache_key)
        response_ms = _record_telemetry(endpoint, "hit", started_at)
        cached = dict(cached_payload)
        cached["generated_at"] = datetime.now(timezone.utc).isoformat()
        cached["meta"] = dict(cached.get("meta") or {})
        cached["meta"]["cache"] = "hit"
        cached["meta"]["telemetry"] = _telemetry_stats(endpoint, response_ms)
        return jsonify(cached)

    current_start, current_end, prev_start, prev_end = _period_offsets(filters)

    with get_session() as db:
        current_orders = _fetch_orders(db, filters, current_start, current_end)
        prev_orders = _fetch_orders(db, filters, prev_start, prev_end)

        current_ids = [o.order_id for o in current_orders]
        prev_ids = [o.order_id for o in prev_orders]
        current_products = _order_products_map(db, current_ids)
        prev_products = _order_products_map(db, prev_ids)

        buckets: dict[str, dict[str, Decimal | int]] = defaultdict(
            lambda: {"revenue": Decimal("0"), "orders": 0, "items": 0}
        )

        for order in current_orders:
            key = _bucket_key(order.date_add or current_start, filters.granularity)
            buckets[key]["revenue"] = Decimal(str(buckets[key]["revenue"])) + _order_revenue(order, current_products)
            buckets[key]["orders"] = int(buckets[key]["orders"]) + 1
            buckets[key]["items"] = int(buckets[key]["items"]) + int(
                current_products.get(order.order_id, {}).get("qty", 0)
            )

        current_revenue = sum((_order_revenue(o, current_products) for o in current_orders), Decimal("0"))
        prev_revenue = sum((_order_revenue(o, prev_products) for o in prev_orders), Decimal("0"))

        cod_count = sum(1 for o in current_orders if _is_cod(o))
        online_count = len(current_orders) - cod_count
        total_count = len(current_orders) or 1

        allegro_count = sum(1 for o in current_orders if (o.platform or "") == "allegro")
        shop_count = sum(1 for o in current_orders if (o.platform or "") == "shop")
        ebay_count = sum(1 for o in current_orders if (o.platform or "") == "ebay")
        manual_count = len(current_orders) - allegro_count - shop_count - ebay_count

    series = [
        {
            "bucket": key,
            "revenue": float(value["revenue"]),
            "orders": int(value["orders"]),
            "items": int(value["items"]),
        }
        for key, value in sorted(buckets.items(), key=lambda x: x[0])
    ]

    payload = {
        "ok": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "filters": _format_filters(filters),
        "data": {
            "series": series,
            "split": {
                "payment": {
                    "cod": round(cod_count / total_count * 100, 2),
                    "online": round(online_count / total_count * 100, 2),
                },
                "platform": {
                    "allegro": round(allegro_count / total_count * 100, 2),
                    "shop": round(shop_count / total_count * 100, 2),
                    "ebay": round(ebay_count / total_count * 100, 2),
                    "manual": round(manual_count / total_count * 100, 2),
                },
            },
            "summary": {
                "revenue": float(current_revenue),
                "orders": len(current_orders),
                "mom": _pct_change(current_revenue, prev_revenue),
            },
        },
        "meta": {
            "confidence": "medium",
            "sources": ["db.orders", "db.order_products"],
            "cache": "miss",
            "telemetry": {},
        },
        "errors": [],
    }
    endpoint = _endpoint_name(cache_key)
    response_ms = _record_telemetry(endpoint, "miss", started_at)
    payload["meta"]["telemetry"] = _telemetry_stats(endpoint, response_ms)
    _cache_set(cache_key, payload)
    return jsonify(payload)


@bp.route("/profit")
@login_required
def stats_profit():
    started_at = time.perf_counter()
    filters, err = _parse_filters()
    if err:
        return err

    cache_key = "profit|" + _build_cache_key(filters)
    cached_payload = _cache_get(cache_key)
    if cached_payload is not None:
        endpoint = _endpoint_name(cache_key)
        response_ms = _record_telemetry(endpoint, "hit", started_at)
        cached = dict(cached_payload)
        cached["generated_at"] = datetime.now(timezone.utc).isoformat()
        cached["meta"] = dict(cached.get("meta") or {})
        cached["meta"]["cache"] = "hit"
        cached["meta"]["telemetry"] = _telemetry_stats(endpoint, response_ms)
        return jsonify(cached)

    with get_session() as db:
        orders = _fetch_orders(db, filters, int(filters.date_from.timestamp()), int(filters.date_to.timestamp()))
        order_ids = [o.order_id for o in orders]
        products_map = _order_products_map(db, order_ids)
        prev_start, prev_end = int((filters.date_from - (filters.date_to - filters.date_from)).timestamp()), int(filters.date_from.timestamp())
        prev_orders = _fetch_orders(db, filters, prev_start, prev_end)
        prev_products = _order_products_map(db, [o.order_id for o in prev_orders])

    current_revenue = sum((_order_revenue(o, products_map) for o in orders), Decimal("0"))
    prev_revenue = sum((_order_revenue(o, prev_products) for o in prev_orders), Decimal("0"))

    access_token = settings_store.get("ALLEGRO_ACCESS_TOKEN")
    with get_session() as db2:
        calculator = FinancialCalculator(db2, settings_store)
        summary = calculator.get_period_summary(
            int(filters.date_from.timestamp()),
            int(filters.date_to.timestamp()),
            access_token=access_token,
        )

    net_profit_cur = Decimal(str(summary.net_profit))
    net_profit_prev_data = Decimal(str(prev_revenue)) - Decimal(str(getattr(summary, "total_purchase_cost", 0) or 0))

    purchase_cost = Decimal(str(summary.total_purchase_cost or 0))
    allegro_fees = Decimal(str(summary.total_allegro_fees or 0))
    packaging_cost = Decimal(str(summary.total_packaging_cost or 0))
    fixed_costs = Decimal(str(summary.fixed_costs or 0))
    ads_cost = Decimal(str(getattr(summary, "ads_cost", 0) or 0))

    waterfall = [
        {"name": "Przychod", "value": float(current_revenue), "cumulative": float(current_revenue)},
        {"name": "Koszty zakupu", "value": -float(purchase_cost), "cumulative": float(current_revenue - purchase_cost)},
        {"name": "Prowizje Allegro", "value": -float(allegro_fees), "cumulative": float(current_revenue - purchase_cost - allegro_fees)},
        {"name": "Koszty pakowania", "value": -float(packaging_cost), "cumulative": float(current_revenue - purchase_cost - allegro_fees - packaging_cost)},
        {"name": "Koszty stale", "value": -float(fixed_costs), "cumulative": float(current_revenue - purchase_cost - allegro_fees - packaging_cost - fixed_costs)},
        {"name": "Reklama", "value": -float(ads_cost), "cumulative": float(net_profit_cur)},
        {"name": "Zysk netto", "value": float(net_profit_cur), "cumulative": float(net_profit_cur)},
    ]

    wow_end = int(filters.date_to.timestamp())
    wow_start = wow_end - 7 * 86400
    wow_prev_end = wow_start
    wow_prev_start = wow_start - 7 * 86400

    wow_orders = []
    wow_prev_orders = []
    with get_session() as db:
        wow_orders = _fetch_orders(db, filters, wow_start, wow_end)
        wow_prev_orders = _fetch_orders(db, filters, wow_prev_start, wow_prev_end)
        wow_pm = _order_products_map(db, [o.order_id for o in wow_orders])
        wow_pm_prev = _order_products_map(db, [o.order_id for o in wow_prev_orders])

    wow_cur_revenue = sum((_order_revenue(o, wow_pm) for o in wow_orders), Decimal("0"))
    wow_prv_revenue = sum((_order_revenue(o, wow_pm_prev) for o in wow_prev_orders), Decimal("0"))

    payload = {
        "ok": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "filters": _format_filters(filters),
        "data": {
            "waterfall": waterfall,
            "summary": {
                "revenue": float(current_revenue),
                "net_profit": float(net_profit_cur),
                "mom": _pct_change(current_revenue, prev_revenue),
                "wow": _pct_change(wow_cur_revenue, wow_prv_revenue),
            },
        },
        "meta": {
            "confidence": "medium",
            "sources": ["db.orders", "db.order_products", "domain.financial"],
            "cache": "miss",
            "telemetry": {},
        },
        "errors": [],
    }
    endpoint = _endpoint_name(cache_key)
    response_ms = _record_telemetry(endpoint, "miss", started_at)
    payload["meta"]["telemetry"] = _telemetry_stats(endpoint, response_ms)
    _cache_set(cache_key, payload)
    return jsonify(payload)


@bp.route("/allegro-costs")
@login_required
def stats_allegro_costs():
    started_at = time.perf_counter()
    filters, err = _parse_filters()
    if err:
        return err

    cache_key = "allegro-costs|" + _build_cache_key(filters)
    cached_payload = _cache_get(cache_key)
    if cached_payload is not None:
        endpoint = _endpoint_name(cache_key)
        response_ms = _record_telemetry(endpoint, "hit", started_at)
        cached = dict(cached_payload)
        cached["generated_at"] = datetime.now(timezone.utc).isoformat()
        cached["meta"] = dict(cached.get("meta") or {})
        cached["meta"]["cache"] = "hit"
        cached["meta"]["telemetry"] = _telemetry_stats(endpoint, response_ms)
        return jsonify(cached)

    access_token = settings_store.get("ALLEGRO_ACCESS_TOKEN")
    if not access_token:
        return _json_error(
            "ALLEGRO_TOKEN_MISSING",
            "Brak tokenu Allegro - nie mozna pobrac kosztow Allegro",
            400,
        )

    from .allegro_api import fetch_billing_entries, fetch_billing_types, get_period_ads_cost

    date_from_iso = filters.date_from.strftime("%Y-%m-%dT00:00:00Z")
    date_to_iso = (filters.date_to - timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ")

    entries_data = fetch_billing_entries(
        access_token,
        occurred_at_gte=date_from_iso,
        occurred_at_lte=date_to_iso,
        limit=100,
    )
    entries = entries_data.get("billingEntries", [])

    types_data = fetch_billing_types(access_token)
    if isinstance(types_data, dict):
        types_list = types_data.get("billingTypes", [])
    else:
        types_list = types_data or []
    api_type_name_map = {
        t.get("id"): t.get("description") or t.get("name") or t.get("id")
        for t in types_list
        if t.get("id")
    }

    agg: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for e in entries:
        t = (e.get("type") or {}).get("id") or "UNKNOWN"
        amount = Decimal(str((e.get("value") or {}).get("amount") or 0))
        if amount < 0:
            agg[t] += abs(amount)

    ads_result = get_period_ads_cost(access_token, date_from_iso, date_to_iso)
    ads_total = Decimal(str(ads_result.get("total_cost") or 0))

    with get_session() as db:
        db_type_name_map = _upsert_billing_types(db, types_list)
        type_name_map = {**db_type_name_map, **api_type_name_map}
        orders = _fetch_orders(db, filters, _to_ts(filters.date_from), _to_ts(filters.date_to))
        order_ids = [o.order_id for o in orders]
        products_map = _order_products_map(db, order_ids)
        revenue = sum((_order_revenue(o, products_map) for o in orders), Decimal("0"))

    allegro_total = sum(agg.values(), Decimal("0"))
    allegro_pct = (allegro_total / revenue * 100) if revenue > 0 else Decimal("0")
    ads_pct = (ads_total / revenue * 100) if revenue > 0 else Decimal("0")

    payload = {
        "ok": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "filters": {
            "date_from": filters.date_from.strftime("%Y-%m-%d"),
            "date_to": (filters.date_to - timedelta(days=1)).strftime("%Y-%m-%d"),
            "granularity": filters.granularity,
            "platform": filters.platform,
            "payment_type": filters.payment_type,
        },
        "data": {
            "fees_by_type": [
                {
                    "type": k,
                    "name": type_name_map.get(k, k),
                    "amount": float(v),
                }
                for k, v in sorted(agg.items(), key=lambda x: str(x[0]))
            ],
            "daily_ads": ads_result.get("daily_costs", []),
            "totals": {
                "allegro_total": float(allegro_total),
                "ads_total": float(ads_total),
                "allegro_pct_revenue": float(allegro_pct),
                "ads_pct_revenue": float(ads_pct),
            },
        },
        "meta": {
            "confidence": "medium",
            "sources": ["allegro.billing", "allegro.ads", "db.orders", "db.order_products"],
            "cache": "miss",
            "telemetry": {},
        },
        "errors": [],
    }
    endpoint = _endpoint_name(cache_key)
    response_ms = _record_telemetry(endpoint, "miss", started_at)
    payload["meta"]["telemetry"] = _telemetry_stats(endpoint, response_ms)
    _cache_set(cache_key, payload)
    return jsonify(payload)


@bp.route("/ads-offer-analytics")
@login_required
def stats_ads_offer_analytics():
    """Priorytet C: rozszerzone dane reklam i offer analytics na bazie dostepnych danych."""
    started_at = time.perf_counter()
    filters, err = _parse_filters()
    if err:
        return err

    export_format = (request.args.get("format") or "").strip().lower()
    if export_format and export_format not in {"csv", "xlsx"}:
        return _json_error("INVALID_EXPORT_FORMAT", "Dozwolone formaty eksportu: csv, xlsx")

    cache_key = "ads-offer-analytics|" + _build_cache_key(filters)
    if not export_format:
        cached_payload = _cache_get(cache_key)
        if cached_payload is not None:
            endpoint = _endpoint_name(cache_key)
            response_ms = _record_telemetry(endpoint, "hit", started_at)
            cached = dict(cached_payload)
            cached["generated_at"] = datetime.now(timezone.utc).isoformat()
            cached["meta"] = dict(cached.get("meta") or {})
            cached["meta"]["cache"] = "hit"
            cached["meta"]["telemetry"] = _telemetry_stats(endpoint, response_ms)
            return jsonify(cached)

    access_token = settings_store.get("ALLEGRO_ACCESS_TOKEN")
    if not access_token:
        return _json_error(
            "ALLEGRO_TOKEN_MISSING",
            "Brak tokenu Allegro - nie mozna pobrac analityki reklam i ofert",
            400,
        )

    from .allegro_api import fetch_billing_entries

    date_from_iso = filters.date_from.strftime("%Y-%m-%dT00:00:00Z")
    date_to_iso = (filters.date_to - timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ")

    entries_data = fetch_billing_entries(
        access_token,
        occurred_at_gte=date_from_iso,
        occurred_at_lte=date_to_iso,
        limit=100,
    )
    entries = entries_data.get("billingEntries", [])

    ads_types = {"NSP", "ADS", "FEA", "DPG", "PRO"}
    promoted_commission_types = {"BRG", "FSF"}
    bonus_types = {"CB2"}

    offer_costs: dict[str, dict[str, Decimal | str]] = {}
    campaign_costs: dict[str, dict[str, Decimal | str]] = {}
    account_level_ads_total = Decimal("0")

    for entry in entries:
        type_id = (entry.get("type") or {}).get("id") or "UNKNOWN"
        amount = Decimal(str((entry.get("value") or {}).get("amount") or 0))
        offer_info = entry.get("offer") or {}
        offer_id = str(offer_info.get("id") or "").strip()
        offer_name = offer_info.get("name") or "-"

        campaign_info = entry.get("campaign") or {}
        campaign_id = str(
            campaign_info.get("id")
            or entry.get("campaignId")
            or entry.get("campaign_id")
            or ""
        ).strip()
        campaign_name = (
            campaign_info.get("name")
            or entry.get("campaignName")
            or entry.get("campaign_name")
            or campaign_id
            or "-"
        )

        if type_id not in (ads_types | promoted_commission_types | bonus_types):
            continue

        if not offer_id:
            if type_id in ads_types and amount < 0:
                account_level_ads_total += abs(amount)
            # Wpisy kampanii bez offer_id nadal moga byc przydatne do agregacji kampanijnej.
            if campaign_id:
                campaign_row = campaign_costs.setdefault(
                    campaign_id,
                    {
                        "campaign_id": campaign_id,
                        "campaign_name": str(campaign_name),
                        "ads_fee": Decimal("0"),
                        "promoted_commission": Decimal("0"),
                        "campaign_bonus": Decimal("0"),
                    },
                )
                if type_id in ads_types and amount < 0:
                    campaign_row["ads_fee"] = Decimal(str(campaign_row["ads_fee"])) + abs(amount)
                elif type_id in promoted_commission_types and amount < 0:
                    campaign_row["promoted_commission"] = Decimal(str(campaign_row["promoted_commission"])) + abs(amount)
                elif type_id in bonus_types and amount > 0:
                    campaign_row["campaign_bonus"] = Decimal(str(campaign_row["campaign_bonus"])) + amount
            continue

        row = offer_costs.setdefault(
            offer_id,
            {
                "offer_id": offer_id,
                "offer_name": str(offer_name),
                "ads_fee": Decimal("0"),
                "promoted_commission": Decimal("0"),
                "campaign_bonus": Decimal("0"),
            },
        )

        if type_id in ads_types and amount < 0:
            row["ads_fee"] = Decimal(str(row["ads_fee"])) + abs(amount)
        elif type_id in promoted_commission_types and amount < 0:
            row["promoted_commission"] = Decimal(str(row["promoted_commission"])) + abs(amount)
        elif type_id in bonus_types and amount > 0:
            row["campaign_bonus"] = Decimal(str(row["campaign_bonus"])) + amount

        if campaign_id:
            campaign_row = campaign_costs.setdefault(
                campaign_id,
                {
                    "campaign_id": campaign_id,
                    "campaign_name": str(campaign_name),
                    "ads_fee": Decimal("0"),
                    "promoted_commission": Decimal("0"),
                    "campaign_bonus": Decimal("0"),
                },
            )
            if type_id in ads_types and amount < 0:
                campaign_row["ads_fee"] = Decimal(str(campaign_row["ads_fee"])) + abs(amount)
            elif type_id in promoted_commission_types and amount < 0:
                campaign_row["promoted_commission"] = Decimal(str(campaign_row["promoted_commission"])) + abs(amount)
            elif type_id in bonus_types and amount > 0:
                campaign_row["campaign_bonus"] = Decimal(str(campaign_row["campaign_bonus"])) + amount

    start_ts = _to_ts(filters.date_from)
    end_ts = _to_ts(filters.date_to)
    with get_session() as db:
        offers_map = {
            o.offer_id: o
            for o in db.query(AllegroOffer).filter(AllegroOffer.offer_id.in_(list(offer_costs.keys()))).all()
        }
        active_offers_total = db.query(AllegroOffer).filter(AllegroOffer.publication_status == "ACTIVE").count()

        orders = _fetch_orders(db, filters, start_ts, end_ts)
        order_ids = [o.order_id for o in orders]

        sales_by_offer: dict[str, dict[str, Decimal | int]] = defaultdict(lambda: {"orders": 0, "items": 0, "revenue": Decimal("0")})
        if order_ids:
            sales_rows = (
                db.query(
                    OrderProduct.auction_id,
                    func.count(func.distinct(OrderProduct.order_id)).label("orders"),
                    func.sum(OrderProduct.quantity).label("items"),
                    func.sum(OrderProduct.price_brutto * OrderProduct.quantity).label("revenue"),
                )
                .filter(
                    OrderProduct.order_id.in_(order_ids),
                    OrderProduct.auction_id.isnot(None),
                )
                .group_by(OrderProduct.auction_id)
                .all()
            )
            for row in sales_rows:
                oid = str(row.auction_id)
                sales_by_offer[oid] = {
                    "orders": int(row.orders or 0),
                    "items": int(row.items or 0),
                    "revenue": Decimal(str(row.revenue or 0)),
                }

    top_rows: list[dict] = []
    total_offer_ads_fee = Decimal("0")
    total_promoted_commission = Decimal("0")
    total_campaign_bonus = Decimal("0")
    offers_with_sales = 0
    total_offer_revenue = Decimal("0")

    for offer_id, row in offer_costs.items():
        ads_fee = Decimal(str(row["ads_fee"]))
        promoted_commission = Decimal(str(row["promoted_commission"]))
        campaign_bonus = Decimal(str(row["campaign_bonus"]))
        net_ads_spend = ads_fee + promoted_commission - campaign_bonus

        total_offer_ads_fee += ads_fee
        total_promoted_commission += promoted_commission
        total_campaign_bonus += campaign_bonus

        offer_db = offers_map.get(offer_id)
        sales = sales_by_offer.get(offer_id, {"orders": 0, "items": 0, "revenue": Decimal("0")})
        if int(sales["orders"]) > 0:
            offers_with_sales += 1
        total_offer_revenue += Decimal(str(sales["revenue"]))

        roas = None
        if net_ads_spend > 0:
            roas = round(float(Decimal(str(sales["revenue"])) / net_ads_spend), 2)

        top_rows.append(
            {
                "offer_id": offer_id,
                "offer_name": row["offer_name"],
                "publication_status": offer_db.publication_status if offer_db else "UNKNOWN",
                "current_price": float(Decimal(str(offer_db.price))) if offer_db and offer_db.price is not None else None,
                "ads_fee": float(ads_fee),
                "promoted_commission": float(promoted_commission),
                "campaign_bonus": float(campaign_bonus),
                "net_ads_spend": float(net_ads_spend),
                "orders_count": int(sales["orders"]),
                "items_sold": int(sales["items"]),
                "revenue": float(Decimal(str(sales["revenue"]))),
                "roas": roas,
            }
        )

    top_rows.sort(key=lambda r: (r["net_ads_spend"], r["ads_fee"]), reverse=True)

    top_campaigns: list[dict] = []
    for row in campaign_costs.values():
        ads_fee = Decimal(str(row["ads_fee"]))
        promoted_commission = Decimal(str(row["promoted_commission"]))
        campaign_bonus = Decimal(str(row["campaign_bonus"]))
        net_ads_spend = ads_fee + promoted_commission - campaign_bonus
        top_campaigns.append(
            {
                "campaign_id": str(row["campaign_id"]),
                "campaign_name": str(row["campaign_name"]),
                "ads_fee": float(ads_fee),
                "promoted_commission": float(promoted_commission),
                "campaign_bonus": float(campaign_bonus),
                "net_ads_spend": float(net_ads_spend),
            }
        )
    top_campaigns.sort(key=lambda item: item["net_ads_spend"], reverse=True)

    net_offer_ads_spend = total_offer_ads_fee + total_promoted_commission - total_campaign_bonus
    roas_offer_level = None
    if net_offer_ads_spend > 0:
        roas_offer_level = round(float(total_offer_revenue / net_offer_ads_spend), 2)

    if export_format:
        export_rows = [
            {
                "offer_id": row["offer_id"],
                "offer_name": row["offer_name"],
                "publication_status": row["publication_status"],
                "current_price": row["current_price"],
                "ads_fee": row["ads_fee"],
                "promoted_commission": row["promoted_commission"],
                "campaign_bonus": row["campaign_bonus"],
                "net_ads_spend": row["net_ads_spend"],
                "orders_count": row["orders_count"],
                "items_sold": row["items_sold"],
                "revenue": row["revenue"],
                "roas": row["roas"],
            }
            for row in top_rows
        ]
        return _export_table(export_rows, "ads_offer_analytics", export_format)

    payload = {
        "ok": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "filters": _format_filters(filters),
        "data": {
            "summary": {
                "account_level_ads_total": float(account_level_ads_total),
                "offer_ads_total": float(total_offer_ads_fee),
                "promoted_commission_total": float(total_promoted_commission),
                "campaign_bonus_total": float(total_campaign_bonus),
                "net_ads_spend_total": float(total_offer_ads_fee + total_promoted_commission - total_campaign_bonus + account_level_ads_total),
                "offers_with_ads_cost": len(offer_costs),
                "active_offers_total": active_offers_total,
                "offers_with_sales": offers_with_sales,
                "offer_attributed_revenue": float(total_offer_revenue),
                "roas_offer_level": roas_offer_level,
                "campaigns_detected": len(campaign_costs),
            },
            "top_offers": top_rows[:12],
            "top_campaigns": top_campaigns[:12],
            "availability": {
                "offer_level_ads_cost": True,
                "campaign_level_ads_cost": len(campaign_costs) > 0,
                "offer_level_views_ctr": False,
                "offer_level_conversion": False,
                "note": "Dostepne: koszty reklam i prowizje promowane z billing entries + dane ofert/sprzedazy z DB. Brak natywnego feedu views/CTR/conversion w obecnej integracji.",
            },
        },
        "meta": {
            "confidence": "medium",
            "sources": ["allegro.billing", "db.allegro_offers", "db.order_products", "db.orders"],
            "cache": "miss",
            "telemetry": {},
        },
        "errors": [],
    }

    endpoint = _endpoint_name(cache_key)
    response_ms = _record_telemetry(endpoint, "miss", started_at)
    payload["meta"]["telemetry"] = _telemetry_stats(endpoint, response_ms)
    _cache_set(cache_key, payload)
    return jsonify(payload)


@bp.route("/refund-timeline")
@login_required
def stats_refund_timeline():
    """KPI czasu przejsc zwrotu od zgloszenia do refundu."""
    started_at = time.perf_counter()
    filters, err = _parse_filters()
    if err:
        return err

    cache_key = "refund-timeline|" + _build_cache_key(filters)
    cached_payload = _cache_get(cache_key)
    if cached_payload is not None:
        endpoint = _endpoint_name(cache_key)
        response_ms = _record_telemetry(endpoint, "hit", started_at)
        cached = dict(cached_payload)
        cached["generated_at"] = datetime.now(timezone.utc).isoformat()
        cached["meta"] = dict(cached.get("meta") or {})
        cached["meta"]["cache"] = "hit"
        cached["meta"]["telemetry"] = _telemetry_stats(endpoint, response_ms)
        return jsonify(cached)

    start_dt = filters.date_from
    end_dt = filters.date_to

    with get_session() as db:
        returns_query = db.query(Return).filter(Return.created_at >= start_dt, Return.created_at < end_dt)
        if filters.platform != "all":
            returns_query = returns_query.join(Order, Return.order_id == Order.order_id).filter(Order.platform == filters.platform)
        returns_data = returns_query.all()

        if filters.payment_type != "all":
            order_ids = [ret.order_id for ret in returns_data if ret.order_id]
            orders_map = {}
            if order_ids:
                orders_map = {o.order_id: o for o in db.query(Order).filter(Order.order_id.in_(order_ids)).all()}
            filtered_returns = []
            for ret in returns_data:
                order = orders_map.get(ret.order_id)
                if not order:
                    continue
                if filters.payment_type == "cod" and _is_cod(order):
                    filtered_returns.append(ret)
                if filters.payment_type == "online" and not _is_cod(order):
                    filtered_returns.append(ret)
            returns_data = filtered_returns

        return_ids = [ret.id for ret in returns_data]
        logs_by_return: dict[int, list[ReturnStatusLog]] = defaultdict(list)
        if return_ids:
            logs = (
                db.query(ReturnStatusLog)
                .filter(ReturnStatusLog.return_id.in_(return_ids))
                .order_by(ReturnStatusLog.return_id.asc(), ReturnStatusLog.timestamp.asc())
                .all()
            )
            for log in logs:
                logs_by_return[log.return_id].append(log)

    request_to_delivered: list[float] = []
    delivered_to_refund: list[float] = []
    request_to_refund: list[float] = []
    delivered_count = 0
    refunded_count = 0

    for ret in returns_data:
        delivered_at = None
        refunded_at = None
        for log in logs_by_return.get(ret.id, []):
            status = (log.status or "").strip().lower()
            if status == "delivered" and delivered_at is None:
                delivered_at = log.timestamp
            if status == "completed" and refunded_at is None:
                refunded_at = log.timestamp

        if delivered_at and ret.created_at and delivered_at >= ret.created_at:
            delivered_count += 1
            request_to_delivered.append((delivered_at - ret.created_at).total_seconds() / 3600)

        if refunded_at and ret.created_at and refunded_at >= ret.created_at:
            refunded_count += 1
            request_to_refund.append((refunded_at - ret.created_at).total_seconds() / 3600)

        if delivered_at and refunded_at and refunded_at >= delivered_at:
            delivered_to_refund.append((refunded_at - delivered_at).total_seconds() / 3600)

    def _metric(values: list[float]) -> dict[str, float | int]:
        if not values:
            return {"count": 0, "avg_hours": 0.0, "median_hours": 0.0, "p95_hours": 0.0}
        sorted_values = sorted(values)
        return {
            "count": len(sorted_values),
            "avg_hours": round(sum(sorted_values) / len(sorted_values), 2),
            "median_hours": round(sorted_values[len(sorted_values) // 2], 2),
            "p95_hours": round(sorted_values[int(0.95 * (len(sorted_values) - 1))], 2),
        }

    payload = {
        "ok": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "filters": _format_filters(filters),
        "data": {
            "summary": {
                "returns_total": len(returns_data),
                "delivered_count": delivered_count,
                "refunded_count": refunded_count,
            },
            "transitions": {
                "request_to_delivered": _metric(request_to_delivered),
                "delivered_to_refund": _metric(delivered_to_refund),
                "request_to_refund": _metric(request_to_refund),
            },
        },
        "meta": {
            "confidence": "medium",
            "sources": ["db.returns", "db.return_status_logs", "db.orders"],
            "cache": "miss",
            "telemetry": {},
        },
        "errors": [],
    }
    endpoint = _endpoint_name(cache_key)
    response_ms = _record_telemetry(endpoint, "miss", started_at)
    payload["meta"]["telemetry"] = _telemetry_stats(endpoint, response_ms)
    _cache_set(cache_key, payload)
    return jsonify(payload)


@bp.route("/returns")
@login_required
def stats_returns():
    started_at = time.perf_counter()
    filters, err = _parse_filters()
    if err:
        return err

    cache_key = "returns|" + _build_cache_key(filters)
    cached_payload = _cache_get(cache_key)
    if cached_payload is not None:
        endpoint = _endpoint_name(cache_key)
        response_ms = _record_telemetry(endpoint, "hit", started_at)
        cached = dict(cached_payload)
        cached["generated_at"] = datetime.now(timezone.utc).isoformat()
        cached["meta"] = dict(cached.get("meta") or {})
        cached["meta"]["cache"] = "hit"
        cached["meta"]["telemetry"] = _telemetry_stats(endpoint, response_ms)
        return jsonify(cached)

    start_ts = _to_ts(filters.date_from)
    end_ts = _to_ts(filters.date_to)
    start_dt = datetime.fromtimestamp(start_ts)
    end_dt = datetime.fromtimestamp(end_ts)

    with get_session() as db:
        orders = _fetch_orders(db, filters, start_ts, end_ts)
        order_ids = {o.order_id for o in orders}

        returns_q = db.query(Return).filter(Return.created_at >= start_dt, Return.created_at < end_dt)
        if filters.platform != "all":
            returns_q = returns_q.join(Order, Return.order_id == Order.order_id).filter(Order.platform == filters.platform)
        returns_data = returns_q.all()

        if filters.payment_type != "all":
            filtered_returns = []
            orders_map = {o.order_id: o for o in orders}
            for ret in returns_data:
                order = orders_map.get(ret.order_id)
                if not order:
                    continue
                if filters.payment_type == "cod" and _is_cod(order):
                    filtered_returns.append(ret)
                if filters.payment_type == "online" and not _is_cod(order):
                    filtered_returns.append(ret)
            returns_data = filtered_returns

        status_counts = {
            "pending": 0,
            "in_transit": 0,
            "delivered": 0,
            "completed": 0,
            "cancelled": 0,
        }
        for ret in returns_data:
            status_counts[ret.status] = status_counts.get(ret.status, 0) + 1

        total_returns = len(returns_data)
        refund_processed = sum(1 for ret in returns_data if bool(ret.refund_processed))
        stock_restored = sum(1 for ret in returns_data if bool(ret.stock_restored))

        returns_rate = (Decimal(str(total_returns)) / Decimal(str(len(order_ids))) * 100) if order_ids else Decimal("0")
        refund_success_rate = (Decimal(str(refund_processed)) / Decimal(str(total_returns)) * 100) if total_returns else Decimal("0")
        stock_restore_rate = (Decimal(str(stock_restored)) / Decimal(str(total_returns)) * 100) if total_returns else Decimal("0")

    alerts = _build_alerts(
        returns_rate=float(returns_rate),
        refund_rate=float(refund_success_rate),
    )

    payload = {
        "ok": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "filters": {
            "date_from": filters.date_from.strftime("%Y-%m-%d"),
            "date_to": (filters.date_to - timedelta(days=1)).strftime("%Y-%m-%d"),
            "granularity": filters.granularity,
            "platform": filters.platform,
            "payment_type": filters.payment_type,
        },
        "data": {
            "summary": {
                "returns_total": total_returns,
                "returns_rate": float(returns_rate),
                "refund_processed": refund_processed,
                "refund_success_rate": float(refund_success_rate),
                "stock_restored": stock_restored,
                "stock_restore_rate": float(stock_restore_rate),
            },
            "status_breakdown": status_counts,
            "alerts": alerts,
        },
        "meta": {
            "confidence": "medium",
            "sources": ["db.returns", "db.orders"],
            "cache": "miss",
            "telemetry": {},
        },
        "errors": [],
    }
    endpoint = _endpoint_name(cache_key)
    response_ms = _record_telemetry(endpoint, "miss", started_at)
    payload["meta"]["telemetry"] = _telemetry_stats(endpoint, response_ms)
    _cache_set(cache_key, payload)
    return jsonify(payload)


@bp.route("/billing-types", methods=["GET"])
@login_required
def stats_billing_types_list():
    with get_session() as db:
        rows = (
            db.query(AllegroBillingType)
            .order_by(AllegroBillingType.type_id.asc())
            .all()
        )

    data = [
        {
            "type_id": row.type_id,
            "name": row.name,
            "description": row.description,
            "mapping_category": row.mapping_category,
            "mapping_version": int(row.mapping_version or 1),
            "last_seen_at": row.last_seen_at.isoformat() if row.last_seen_at else None,
        }
        for row in rows
    ]
    return jsonify(
        {
            "ok": True,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "data": {
                "rows": data,
                "categories": sorted(BILLING_CATEGORY_CHOICES),
            },
            "errors": [],
        }
    )


@bp.route("/billing-types/<string:type_id>", methods=["PUT"])
@login_required
def stats_billing_type_update(type_id: str):
    payload = request.get_json(silent=True) or {}
    new_category = (payload.get("mapping_category") or "").strip()
    if new_category not in BILLING_CATEGORY_CHOICES:
        return _json_error(
            "INVALID_MAPPING_CATEGORY",
            "Niepoprawna kategoria mapowania billing type",
            400,
        )

    with get_session() as db:
        row = db.query(AllegroBillingType).filter(AllegroBillingType.type_id == type_id).first()
        if row is None:
            return _json_error("BILLING_TYPE_NOT_FOUND", "Nie znaleziono billing type", 404)

        if row.mapping_category != new_category:
            row.mapping_category = new_category
            row.mapping_version = int(row.mapping_version or 1) + 1
            db.flush()

        result = {
            "type_id": row.type_id,
            "mapping_category": row.mapping_category,
            "mapping_version": int(row.mapping_version or 1),
        }

    return jsonify(
        {
            "ok": True,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "data": result,
            "errors": [],
        }
    )


@bp.route("/billing-types/sync", methods=["POST"])
@login_required
def stats_billing_types_sync():
    access_token = settings_store.get("ALLEGRO_ACCESS_TOKEN")
    if not access_token:
        return _json_error("ALLEGRO_TOKEN_MISSING", "Brak tokenu Allegro", 400)

    result = sync_billing_types_dictionary(access_token)
    return jsonify(
        {
            "ok": True,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "data": result,
            "errors": [],
        }
    )


@bp.route("/logistics")
@login_required
def stats_logistics():
    started_at = time.perf_counter()
    filters, err = _parse_filters()
    if err:
        return err

    cache_key = "logistics|" + _build_cache_key(filters)
    cached_payload = _cache_get(cache_key)
    if cached_payload is not None:
        endpoint = _endpoint_name(cache_key)
        response_ms = _record_telemetry(endpoint, "hit", started_at)
        cached = dict(cached_payload)
        cached["generated_at"] = datetime.now(timezone.utc).isoformat()
        cached["meta"] = dict(cached.get("meta") or {})
        cached["meta"]["cache"] = "hit"
        cached["meta"]["telemetry"] = _telemetry_stats(endpoint, response_ms)
        return jsonify(cached)

    start_ts = _to_ts(filters.date_from)
    end_ts = _to_ts(filters.date_to)
    start_dt = datetime.fromtimestamp(start_ts)
    end_dt = datetime.fromtimestamp(end_ts)

    start_statuses = {"spakowano", "wyslano"}
    end_statuses = {"dostarczono"}

    with get_session() as db:
        orders = _fetch_orders(db, filters, start_ts, end_ts)
        order_ids = [o.order_id for o in orders]
        orders_map = {o.order_id: o for o in orders}

        logs = []
        if order_ids:
            logs = (
                db.query(OrderStatusLog)
                .filter(
                    OrderStatusLog.order_id.in_(order_ids),
                    OrderStatusLog.timestamp >= start_dt,
                    OrderStatusLog.timestamp < end_dt,
                )
                .order_by(OrderStatusLog.timestamp.asc())
                .all()
            )

        ship_start: dict[str, datetime] = {}
        ship_end: dict[str, datetime] = {}
        status_counts: dict[str, int] = defaultdict(int)

        for log in logs:
            status = (log.status or "").strip().lower()
            status_counts[status] += 1
            if status in start_statuses and log.order_id not in ship_start:
                ship_start[log.order_id] = log.timestamp
            if status in end_statuses:
                ship_end[log.order_id] = log.timestamp

        lead_times_hours: list[float] = []
        lead_time_by_order: dict[str, float] = {}
        for order_id, ship_started_at in ship_start.items():
            delivered_at = ship_end.get(order_id)
            if not delivered_at or delivered_at < ship_started_at:
                continue
            lead_hours = (delivered_at - ship_started_at).total_seconds() / 3600
            lead_times_hours.append(lead_hours)
            lead_time_by_order[order_id] = lead_hours

        shipped_total = sum(1 for o in orders if o.delivery_package_nr)
        delivered_total = sum(1 for oid in ship_end.keys() if oid in orders_map)
        in_transit = max(shipped_total - delivered_total, 0)

        by_carrier_raw: dict[str, dict[str, object]] = defaultdict(
            lambda: {"carrier": "", "shipped_total": 0, "delivered_total": 0, "lead_times": []}
        )
        by_delivery_method_raw: dict[str, dict[str, object]] = defaultdict(
            lambda: {
                "carrier": "",
                "delivery_method": "",
                "shipped_total": 0,
                "delivered_total": 0,
                "lead_times": [],
            }
        )

        for order in orders:
            shipped = bool(order.delivery_package_nr or order.order_id in ship_start)
            delivered = order.order_id in ship_end
            carrier = _carrier_label(order)
            delivery_method = _delivery_method_label(order)

            carrier_row = by_carrier_raw[carrier]
            carrier_row["carrier"] = carrier
            if shipped:
                carrier_row["shipped_total"] = int(carrier_row["shipped_total"]) + 1
            if delivered:
                carrier_row["delivered_total"] = int(carrier_row["delivered_total"]) + 1
            if order.order_id in lead_time_by_order:
                carrier_row["lead_times"].append(lead_time_by_order[order.order_id])

            method_key = f"{carrier}|{delivery_method}"
            method_row = by_delivery_method_raw[method_key]
            method_row["carrier"] = carrier
            method_row["delivery_method"] = delivery_method
            if shipped:
                method_row["shipped_total"] = int(method_row["shipped_total"]) + 1
            if delivered:
                method_row["delivered_total"] = int(method_row["delivered_total"]) + 1
            if order.order_id in lead_time_by_order:
                method_row["lead_times"].append(lead_time_by_order[order.order_id])

        avg_lead = sum(lead_times_hours) / len(lead_times_hours) if lead_times_hours else 0.0
        p95_lead = sorted(lead_times_hours)[int(0.95 * (len(lead_times_hours) - 1))] if lead_times_hours else 0.0
        on_time_rate = (
            (sum(1 for v in lead_times_hours if v <= 48.0) / len(lead_times_hours)) * 100
            if lead_times_hours
            else 0.0
        )

    alerts = _build_alerts(lead_time_hours=float(avg_lead))

    payload = {
        "ok": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "filters": _format_filters(filters),
        "data": {
            "summary": {
                "shipped_total": shipped_total,
                "delivered_total": delivered_total,
                "in_transit": in_transit,
                "avg_lead_time_hours": round(avg_lead, 2),
                "p95_lead_time_hours": round(p95_lead, 2),
                "on_time_rate_48h": round(on_time_rate, 2),
            },
            "status_events": dict(status_counts),
            "funnel": [
                {"status": s, "count": status_counts.get(s, 0)}
                for s in ["wydrukowano", "spakowano", "wyslano", "dostarczono"]
            ],
            "error_counts": {
                "blad_druku": status_counts.get("blad_druku", 0),
                "problem_z_dostawa": status_counts.get("problem_z_dostawa", 0),
                "zwrot": status_counts.get("zwrot", 0),
            },
            "by_carrier": _group_logistics_rows(by_carrier_raw),
            "by_delivery_method": _group_logistics_rows(by_delivery_method_raw),
            "alerts": alerts,
        },
        "meta": {
            "confidence": "medium",
            "sources": ["db.orders", "db.order_status_logs"],
            "cache": "miss",
            "telemetry": {},
        },
        "errors": [],
    }
    endpoint = _endpoint_name(cache_key)
    response_ms = _record_telemetry(endpoint, "miss", started_at)
    payload["meta"]["telemetry"] = _telemetry_stats(endpoint, response_ms)
    _cache_set(cache_key, payload)
    return jsonify(payload)


@bp.route("/products")
@login_required
def stats_products():
    started_at = time.perf_counter()
    filters, err = _parse_filters()
    if err:
        return err

    export_format = (request.args.get("format") or "").strip().lower()
    if export_format and export_format not in {"csv", "xlsx"}:
        return _json_error("INVALID_EXPORT_FORMAT", "Dozwolone formaty eksportu: csv, xlsx")

    cache_key = "products|" + _build_cache_key(filters)
    if not export_format:
        cached_payload = _cache_get(cache_key)
        if cached_payload is not None:
            endpoint = _endpoint_name(cache_key)
            response_ms = _record_telemetry(endpoint, "hit", started_at)
            cached = dict(cached_payload)
            cached["generated_at"] = datetime.now(timezone.utc).isoformat()
            cached["meta"] = dict(cached.get("meta") or {})
            cached["meta"]["cache"] = "hit"
            cached["meta"]["telemetry"] = _telemetry_stats(endpoint, response_ms)
            return jsonify(cached)

    start_ts = _to_ts(filters.date_from)
    end_ts = _to_ts(filters.date_to)

    with get_session() as db:
        orders = _fetch_orders(db, filters, start_ts, end_ts)
        order_ids = [o.order_id for o in orders]

        rows = []
        if order_ids:
            rows = (
                db.query(
                    OrderProduct.ean,
                    OrderProduct.name,
                    func.sum(OrderProduct.quantity).label("items"),
                    func.sum(OrderProduct.price_brutto * OrderProduct.quantity).label("gross"),
                    func.count(func.distinct(OrderProduct.order_id)).label("orders_count"),
                    func.sum(
                        case(
                            (
                                or_(
                                    Order.payment_method_cod.is_(True),
                                    func.lower(func.coalesce(Order.payment_method, "")).like("%pobranie%"),
                                ),
                                1,
                            ),
                            else_=0,
                        )
                    ).label("cod_orders"),
                )
                .join(Order, Order.order_id == OrderProduct.order_id)
                .filter(OrderProduct.order_id.in_(order_ids))
                .group_by(OrderProduct.ean, OrderProduct.name)
                .all()
            )

        result_rows = []
        for row in rows:
            total_orders = int(row.orders_count or 0)
            cod_orders = int(row.cod_orders or 0)
            cod_share = (cod_orders / total_orders * 100) if total_orders else 0
            recommendation = "hold"
            if total_orders >= 5 and cod_share < 25:
                recommendation = "raise_2pct"
            elif cod_share > 60:
                recommendation = "review_margin"

            result_rows.append(
                {
                    "ean": row.ean or "",
                    "name": row.name or "",
                    "items_sold": int(row.items or 0),
                    "revenue_gross": float(row.gross or 0),
                    "orders": total_orders,
                    "cod_share": round(cod_share, 2),
                    "repricing_recommendation": recommendation,
                }
            )

    result_rows.sort(key=lambda x: x["revenue_gross"], reverse=True)

    if export_format:
        return _export_table(result_rows, "stats-products", export_format)

    payload = {
        "ok": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "filters": _format_filters(filters),
        "data": {
            "rows": result_rows,
            "summary": {
                "items": len(result_rows),
                "total_revenue": round(sum(r["revenue_gross"] for r in result_rows), 2),
            },
        },
        "meta": {
            "confidence": "medium",
            "sources": ["db.orders", "db.order_products"],
            "cache": "miss",
            "telemetry": {},
        },
        "errors": [],
    }
    endpoint = _endpoint_name(cache_key)
    response_ms = _record_telemetry(endpoint, "miss", started_at)
    payload["meta"]["telemetry"] = _telemetry_stats(endpoint, response_ms)
    _cache_set(cache_key, payload)
    return jsonify(payload)


@bp.route("/competition")
@login_required
def stats_competition():
    started_at = time.perf_counter()
    filters, err = _parse_filters()
    if err:
        return err

    export_format = (request.args.get("format") or "").strip().lower()
    if export_format and export_format not in {"csv", "xlsx"}:
        return _json_error("INVALID_EXPORT_FORMAT", "Dozwolone formaty eksportu: csv, xlsx")

    cache_key = "competition|" + _build_cache_key(filters)
    if not export_format:
        cached_payload = _cache_get(cache_key)
        if cached_payload is not None:
            endpoint = _endpoint_name(cache_key)
            response_ms = _record_telemetry(endpoint, "hit", started_at)
            cached = dict(cached_payload)
            cached["generated_at"] = datetime.now(timezone.utc).isoformat()
            cached["meta"] = dict(cached.get("meta") or {})
            cached["meta"]["cache"] = "hit"
            cached["meta"]["telemetry"] = _telemetry_stats(endpoint, response_ms)
            return jsonify(cached)

    start_ts = _to_ts(filters.date_from)
    end_ts = _to_ts(filters.date_to)
    start_dt = datetime.fromtimestamp(start_ts)
    end_dt = datetime.fromtimestamp(end_ts)
    start_str = filters.date_from.strftime("%Y-%m-%d")
    end_str = filters.date_to.strftime("%Y-%m-%d")

    with get_session() as db:
        report_rows = (
            db.query(
                PriceReportItem.offer_id,
                func.avg(PriceReportItem.our_price).label("our_price"),
                func.avg(PriceReportItem.competitor_price).label("competitor_price"),
                func.avg(PriceReportItem.our_position).label("our_position"),
                func.count(PriceReportItem.id).label("checks"),
            )
            .filter(
                PriceReportItem.checked_at >= start_dt,
                PriceReportItem.checked_at < end_dt,
            )
            .group_by(PriceReportItem.offer_id)
            .all()
        )

        history_rows = (
            db.query(
                AllegroPriceHistory.offer_id,
                func.avg(AllegroPriceHistory.price).label("our_history_price"),
                func.avg(AllegroPriceHistory.competitor_price).label("competitor_history_price"),
            )
            .filter(
                AllegroPriceHistory.recorded_at >= start_str,
                AllegroPriceHistory.recorded_at < end_str,
            )
            .group_by(AllegroPriceHistory.offer_id)
            .all()
        )

    history_map = {
        r.offer_id: {
            "our_history_price": float(r.our_history_price or 0),
            "competitor_history_price": float(r.competitor_history_price or 0),
        }
        for r in history_rows
    }

    rows = []
    for r in report_rows:
        our_price = float(r.our_price or 0)
        competitor_price = float(r.competitor_price or 0)
        price_gap = round(our_price - competitor_price, 2)
        hist = history_map.get(r.offer_id, {})
        recommendation = "hold"
        if competitor_price > 0 and our_price > competitor_price * 1.05:
            recommendation = "decrease_3pct"
        elif competitor_price > 0 and our_price < competitor_price * 0.9:
            recommendation = "increase_2pct"

        rows.append(
            {
                "offer_id": r.offer_id,
                "our_price": round(our_price, 2),
                "competitor_price": round(competitor_price, 2),
                "price_gap": price_gap,
                "our_position": float(r.our_position or 0),
                "checks": int(r.checks or 0),
                "our_history_price": round(hist.get("our_history_price", 0), 2),
                "competitor_history_price": round(hist.get("competitor_history_price", 0), 2),
                "repricing_recommendation": recommendation,
            }
        )

    rows.sort(key=lambda x: abs(x["price_gap"]), reverse=True)

    if export_format:
        return _export_table(rows, "stats-competition", export_format)

    payload = {
        "ok": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "filters": _format_filters(filters),
        "data": {
            "rows": rows,
            "summary": {
                "offers": len(rows),
                "avg_position": round(sum(r["our_position"] for r in rows) / len(rows), 2) if rows else 0,
            },
        },
        "meta": {
            "confidence": "medium",
            "sources": ["db.price_report_items", "db.allegro_price_history"],
            "cache": "miss",
            "telemetry": {},
        },
        "errors": [],
    }
    endpoint = _endpoint_name(cache_key)
    response_ms = _record_telemetry(endpoint, "miss", started_at)
    payload["meta"]["telemetry"] = _telemetry_stats(endpoint, response_ms)
    _cache_set(cache_key, payload)
    return jsonify(payload)


@bp.route("/offer-publication-history")
@login_required
def stats_offer_publication_history():
    started_at = time.perf_counter()
    filters, err = _parse_filters()
    if err:
        return err

    cache_key = "offer-publication-history|" + _build_cache_key(filters)
    cached_payload = _cache_get(cache_key)
    if cached_payload is not None:
        endpoint = _endpoint_name(cache_key)
        response_ms = _record_telemetry(endpoint, "hit", started_at)
        cached = dict(cached_payload)
        cached["generated_at"] = datetime.now(timezone.utc).isoformat()
        cached["meta"] = dict(cached.get("meta") or {})
        cached["meta"]["cache"] = "hit"
        cached["meta"]["telemetry"] = _telemetry_stats(endpoint, response_ms)
        return jsonify(cached)

    start_str = filters.date_from.strftime("%Y-%m-%d")
    end_str = filters.date_to.strftime("%Y-%m-%d")

    with get_session() as db:
        history_rows = (
            db.query(
                AllegroPriceHistory.offer_id,
                AllegroPriceHistory.price,
                AllegroPriceHistory.recorded_at,
            )
            .filter(
                AllegroPriceHistory.recorded_at >= start_str,
                AllegroPriceHistory.recorded_at < end_str,
            )
            .order_by(
                AllegroPriceHistory.offer_id.asc(),
                AllegroPriceHistory.recorded_at.asc(),
            )
            .all()
        )

        offers = (
            db.query(
                AllegroOffer.offer_id,
                AllegroOffer.title,
                AllegroOffer.publication_status,
                AllegroOffer.price,
            )
            .all()
        )

    offers_map = {
        row.offer_id: {
            "title": row.title,
            "publication_status": row.publication_status or "UNKNOWN",
            "current_price": float(row.price or 0),
        }
        for row in offers
        if row.offer_id
    }

    per_day: dict[str, dict[str, object]] = defaultdict(
        lambda: {
            "offers": set(),
            "prices_sum": 0.0,
            "rows": 0,
            "price_change_events": 0,
        }
    )
    per_offer: dict[str, dict[str, object]] = defaultdict(
        lambda: {
            "prices": [],
            "changes": 0,
            "last_price": None,
            "observations": 0,
        }
    )

    for row in history_rows:
        offer_id = (row.offer_id or "").strip()
        if not offer_id:
            continue
        day = str(row.recorded_at or "")[:10]
        if len(day) != 10:
            continue

        price = float(row.price or 0)
        day_row = per_day[day]
        day_row["offers"].add(offer_id)
        day_row["prices_sum"] = float(day_row["prices_sum"]) + price
        day_row["rows"] = int(day_row["rows"]) + 1

        offer_row = per_offer[offer_id]
        offer_row["prices"].append({"day": day, "price": price})
        offer_row["observations"] = int(offer_row["observations"]) + 1
        if offer_row["last_price"] is not None and float(offer_row["last_price"]) != price:
            offer_row["changes"] = int(offer_row["changes"]) + 1
            day_row["price_change_events"] = int(day_row["price_change_events"]) + 1
        offer_row["last_price"] = price

    daily_series = []
    for day in sorted(per_day.keys()):
        day_row = per_day[day]
        rows_total = int(day_row["rows"]) or 1
        daily_series.append(
            {
                "date": day,
                "offers_observed": len(day_row["offers"]),
                "avg_price": round(float(day_row["prices_sum"]) / rows_total, 2),
                "price_change_events": int(day_row["price_change_events"]),
            }
        )

    changed_offers = []
    for offer_id, row in per_offer.items():
        prices = row["prices"]
        if not prices:
            continue
        first_price = float(prices[0]["price"])
        last_price = float(prices[-1]["price"])
        delta = round(last_price - first_price, 2)
        if delta == 0 and int(row["changes"]) == 0:
            continue

        info = offers_map.get(offer_id, {})
        pct_change = round((delta / first_price) * 100, 2) if first_price else 0.0
        changed_offers.append(
            {
                "offer_id": offer_id,
                "title": info.get("title") or offer_id,
                "publication_status": info.get("publication_status") or "UNKNOWN",
                "first_price": round(first_price, 2),
                "last_price": round(last_price, 2),
                "delta": delta,
                "pct_change": pct_change,
                "change_events": int(row["changes"]),
                "observations": int(row["observations"]),
            }
        )

    changed_offers.sort(key=lambda item: abs(float(item["delta"])), reverse=True)

    status_breakdown: dict[str, int] = defaultdict(int)
    for info in offers_map.values():
        status_breakdown[str(info.get("publication_status") or "UNKNOWN")] += 1

    payload = {
        "ok": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "filters": _format_filters(filters),
        "data": {
            "summary": {
                "offers_total": len(offers_map),
                "offers_with_history": len(per_offer),
                "offers_with_price_change": len(changed_offers),
                "price_change_events_total": int(sum(item["change_events"] for item in changed_offers)),
            },
            "publication_status": dict(status_breakdown),
            "daily_series": daily_series,
            "top_changed_offers": changed_offers[:12],
        },
        "meta": {
            "confidence": "medium",
            "sources": ["db.allegro_offers", "db.allegro_price_history"],
            "cache": "miss",
            "telemetry": {},
        },
        "errors": [],
    }

    endpoint = _endpoint_name(cache_key)
    response_ms = _record_telemetry(endpoint, "miss", started_at)
    payload["meta"]["telemetry"] = _telemetry_stats(endpoint, response_ms)
    _cache_set(cache_key, payload)
    return jsonify(payload)


@bp.route("/telemetry")
@login_required
def stats_telemetry():
    data = {}
    for endpoint, entry in _TELEMETRY.items():
        requests_total = int(entry["requests"]) or 1
        cache_hit_ratio = round(entry["cache_hits"] / requests_total * 100, 2)
        avg_response_ms = round(entry["total_response_ms"] / requests_total, 2)
        data[endpoint] = {
            "requests": int(entry["requests"]),
            "cache_hits": int(entry["cache_hits"]),
            "cache_misses": int(entry["cache_misses"]),
            "cache_hit_ratio": cache_hit_ratio,
            "avg_response_ms": avg_response_ms,
        }
    return jsonify(
        {
            "ok": True,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "data": data,
            "errors": [],
        }
    )


@bp.route("/order-funnel")
@login_required
def stats_order_funnel():
    """Funnel analizy dla zamowien - czasy przejscia miedzy statusami na podstawie raw events.
    
    Zwraca:
    - funnel: lista etapow z kontami i czasami srednich przejsc
    - transitions: szczegoly czasow przejsc BOUGHT -> FILLED_IN -> READY_FOR_PROCESSING
    - summary: statystyki ogolne (total_orders, avg_time_to_ready, etc.)
    """
    from .models import OrderEvent, Order
    
    started_at = time.perf_counter()
    filters, err = _parse_filters()
    if err:
        return err

    cache_key = "order-funnel|" + _build_cache_key(filters)
    cached_payload = _cache_get(cache_key)
    if cached_payload is not None:
        endpoint = _endpoint_name(cache_key)
        response_ms = _record_telemetry(endpoint, "hit", started_at)
        cached = dict(cached_payload)
        cached["generated_at"] = datetime.now(timezone.utc).isoformat()
        cached["meta"] = dict(cached.get("meta") or {})
        cached["meta"]["cache"] = "hit"
        cached["meta"]["telemetry"] = _telemetry_stats(endpoint, response_ms)
        return jsonify(cached)

    start_dt = filters.date_from
    end_dt = filters.date_to + timedelta(days=1)

    with get_session() as db:
        # Pobierz wszystkie orders w zakresie czasowym
        orders = _fetch_orders(db, filters, _to_ts(start_dt), _to_ts(end_dt))
        order_ids = {o.order_id for o in orders}

        # Pobierz events dla tych orders
        events = (
            db.query(OrderEvent)
            .filter(
                OrderEvent.order_id.in_(order_ids),
                OrderEvent.occurred_at >= start_dt,
                OrderEvent.occurred_at < end_dt,
            )
            .order_by(OrderEvent.order_id.asc(), OrderEvent.occurred_at.asc())
            .all()
        )

        # Pogrupuj events po order_id
        events_by_order: dict[str, list[OrderEvent]] = defaultdict(list)
        for event in events:
            events_by_order[event.order_id].append(event)

        # Zdefiniuj etapy funnelu i ich order
        funnel_stages = ["BOUGHT", "FILLED_IN", "READY_FOR_PROCESSING"]
        
        # Zlicz ile zamowien bylo w kazdym etapie
        stage_counts: dict[str, int] = defaultdict(int)
        
        # Zbierz czasy przejsc miedzy etapami
        transitions: dict[str, list[float]] = {
            "BOUGHT_to_FILLED_IN": [],
            "FILLED_IN_to_READY_FOR_PROCESSING": [],
            "BOUGHT_to_READY_FOR_PROCESSING": [],
        }

        for order_id, order_events in events_by_order.items():
            # Stwórz mapę event_type -> pierwszy occurrence (czasem)
            event_map: dict[str, datetime] = {}
            for event in order_events:
                if event.event_type not in event_map:
                    event_map[event.event_type] = event.occurred_at

            # Zlicz etapy
            for stage in funnel_stages:
                if stage in event_map:
                    stage_counts[stage] += 1

            # Oblicz czasy przejsc w godzinach
            if "BOUGHT" in event_map and "FILLED_IN" in event_map:
                delta = (event_map["FILLED_IN"] - event_map["BOUGHT"]).total_seconds() / 3600
                transitions["BOUGHT_to_FILLED_IN"].append(delta)

            if "FILLED_IN" in event_map and "READY_FOR_PROCESSING" in event_map:
                delta = (event_map["READY_FOR_PROCESSING"] - event_map["FILLED_IN"]).total_seconds() / 3600
                transitions["FILLED_IN_to_READY_FOR_PROCESSING"].append(delta)

            if "BOUGHT" in event_map and "READY_FOR_PROCESSING" in event_map:
                delta = (event_map["READY_FOR_PROCESSING"] - event_map["BOUGHT"]).total_seconds() / 3600
                transitions["BOUGHT_to_READY_FOR_PROCESSING"].append(delta)

        # Oblicz statystyki przejsc
        transition_stats = {}
        for transition_name, times in transitions.items():
            if times:
                avg_time = sum(times) / len(times)
                median_time = sorted(times)[len(times) // 2] if times else 0
                min_time = min(times)
                max_time = max(times)
                p95_time = sorted(times)[int(0.95 * (len(times) - 1))] if times else 0
                transition_stats[transition_name] = {
                    "count": len(times),
                    "avg_hours": round(avg_time, 2),
                    "median_hours": round(median_time, 2),
                    "min_hours": round(min_time, 2),
                    "max_hours": round(max_time, 2),
                    "p95_hours": round(p95_time, 2),
                }
            else:
                transition_stats[transition_name] = {
                    "count": 0,
                    "avg_hours": 0,
                    "median_hours": 0,
                    "min_hours": 0,
                    "max_hours": 0,
                    "p95_hours": 0,
                }

        # Zbuduj funnel
        funnel = []
        for i, stage in enumerate(funnel_stages):
            count = stage_counts.get(stage, 0)
            if i == 0:
                funnel.append({
                    "stage": stage,
                    "count": count,
                    "conversion_rate": 100.0 if len(orders) == 0 else (count / len(orders)) * 100,
                })
            else:
                prev_stage = funnel_stages[i - 1]
                prev_count = stage_counts.get(prev_stage, 1)
                conversion = (count / prev_count * 100) if prev_count > 0 else 0
                funnel.append({
                    "stage": stage,
                    "count": count,
                    "conversion_rate": conversion,
                })

        result = {
            "total_orders": len(orders),
            "orders_with_events": len(events_by_order),
            "funnel": funnel,
            "transitions": transition_stats,
            "summary": {
                "avg_time_bought_to_ready_hours": round(
                    sum(transitions["BOUGHT_to_READY_FOR_PROCESSING"]) / len(transitions["BOUGHT_to_READY_FOR_PROCESSING"]), 2
                ) if transitions["BOUGHT_to_READY_FOR_PROCESSING"] else 0,
                "median_time_bought_to_ready_hours": round(
                    sorted(transitions["BOUGHT_to_READY_FOR_PROCESSING"])[
                        len(transitions["BOUGHT_to_READY_FOR_PROCESSING"]) // 2
                    ], 2
                ) if transitions["BOUGHT_to_READY_FOR_PROCESSING"] else 0,
            }
        }

        _cache_set(cache_key, result)

    endpoint = _endpoint_name(cache_key)
    response_ms = _record_telemetry(endpoint, "miss", started_at)

    return jsonify(
        {
            "ok": True,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "data": result,
            "errors": [],
            "meta": {
                "cache": "miss",
                "telemetry": _telemetry_stats(endpoint, response_ms),
            },
        }
    )


@bp.route("/shipment-errors")
@login_required
def stats_shipment_errors():
    """Shipment errors KPI - błędy przy generowaniu etykiet i tworzeniu przesyłek.
    
    Zwraca:
    - by_error_type: Liczba błędów per typ (label_generation_failed, invalid_address, etc.)
    - by_delivery_method: Liczba błędów per metoda dostawy (inpost, dhl, orlen, etc.)
    - unresolved: Liczba nierozwiązanych błędów
    - unresolved_by_type: Nierozwiązane błędy grouped by type
    """
    from .models import ShipmentError
    
    started_at = time.perf_counter()
    filters, err = _parse_filters()
    if err:
        return err

    cache_key = "shipment-errors|" + _build_cache_key(filters)
    cached_payload = _cache_get(cache_key)
    if cached_payload is not None:
        endpoint = _endpoint_name(cache_key)
        response_ms = _record_telemetry(endpoint, "hit", started_at)
        cached = dict(cached_payload)
        cached["generated_at"] = datetime.now(timezone.utc).isoformat()
        cached["meta"] = dict(cached.get("meta") or {})
        cached["meta"]["cache"] = "hit"
        cached["meta"]["telemetry"] = _telemetry_stats(endpoint, response_ms)
        return jsonify(cached)

    start_dt = filters.date_from
    end_dt = filters.date_to + timedelta(days=1)

    with get_session() as db:
        # Fetch all shipment errors in period
        all_errors = (
            db.query(ShipmentError)
            .filter(
                ShipmentError.created_at >= start_dt,
                ShipmentError.created_at < end_dt,
            )
            .all()
        )

        # Group by error_type
        by_error_type: dict[str, int] = defaultdict(int)
        by_delivery_method: dict[str, int] = defaultdict(int)
        unresolved_by_type: dict[str, int] = defaultdict(int)
        
        for error in all_errors:
            error_type = error.error_type or "unknown"
            delivery_method = error.delivery_method or "unknown"
            
            by_error_type[error_type] += 1
            by_delivery_method[delivery_method] += 1
            
            if not error.resolved:
                unresolved_by_type[error_type] += 1

        unresolved_count = sum(1 for e in all_errors if not e.resolved)

        result = {
            "total_errors": len(all_errors),
            "unresolved_total": unresolved_count,
            "by_error_type": dict(sorted(by_error_type.items(), key=lambda x: x[1], reverse=True)),
            "by_delivery_method": dict(sorted(by_delivery_method.items(), key=lambda x: x[1], reverse=True)),
            "unresolved_by_type": dict(sorted(unresolved_by_type.items(), key=lambda x: x[1], reverse=True)),
            "summary": {
                "most_common_error": max(by_error_type.items(), key=lambda x: x[1])[0] if by_error_type else "none",
                "most_problematic_courier": max(by_delivery_method.items(), key=lambda x: x[1])[0] if by_delivery_method else "none",
                "resolution_rate": (
                    ((len(all_errors) - unresolved_count) / len(all_errors)) * 100
                ) if all_errors else 0,
            },
        }

        _cache_set(cache_key, result)

    endpoint = _endpoint_name(cache_key)
    response_ms = _record_telemetry(endpoint, "miss", started_at)

    return jsonify(
        {
            "ok": True,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "data": result,
            "errors": [],
            "meta": {
                "cache": "miss",
                "telemetry": _telemetry_stats(endpoint, response_ms),
            },
        }
    )


@bp.route("/customer-support")
@login_required
def stats_customer_support():
    """KPI obslugi klienta na bazie watkow i wiadomosci."""
    started_at = time.perf_counter()
    filters, err = _parse_filters()
    if err:
        return err

    cache_key = "customer-support|" + _build_cache_key(filters)
    cached_payload = _cache_get(cache_key)
    if cached_payload is not None:
        endpoint = _endpoint_name(cache_key)
        response_ms = _record_telemetry(endpoint, "hit", started_at)
        cached = dict(cached_payload)
        cached["generated_at"] = datetime.now(timezone.utc).isoformat()
        cached["meta"] = dict(cached.get("meta") or {})
        cached["meta"]["cache"] = "hit"
        cached["meta"]["telemetry"] = _telemetry_stats(endpoint, response_ms)
        return jsonify(cached)

    start_dt = filters.date_from
    end_dt = filters.date_to

    with get_session() as db:
        threads = (
            db.query(Thread)
            .filter(
                Thread.last_message_at >= start_dt,
                Thread.last_message_at < end_dt,
            )
            .all()
        )

        thread_ids = [t.id for t in threads]
        messages: list[Message] = []
        if thread_ids:
            messages = (
                db.query(Message)
                .filter(Message.thread_id.in_(thread_ids))
                .order_by(Message.thread_id.asc(), Message.created_at.asc())
                .all()
            )

        messages_by_thread: dict[str, list[Message]] = defaultdict(list)
        for msg in messages:
            messages_by_thread[msg.thread_id].append(msg)

        unread_total = 0
        by_type_total: dict[str, int] = defaultdict(int)
        unread_by_type: dict[str, int] = defaultdict(int)
        first_response_hours: list[float] = []

        for thread in threads:
            thread_type = (thread.type or "unknown").strip() or "unknown"
            by_type_total[thread_type] += 1
            if not thread.read:
                unread_total += 1
                unread_by_type[thread_type] += 1

            thread_messages = messages_by_thread.get(thread.id, [])
            if len(thread_messages) < 2:
                continue

            first_msg = thread_messages[0]
            first_customer_author = first_msg.author or thread.author
            first_customer_at = first_msg.created_at
            if not first_customer_at:
                continue

            first_response = next(
                (
                    msg
                    for msg in thread_messages[1:]
                    if msg.created_at and (msg.author or "") != (first_customer_author or "")
                ),
                None,
            )
            if not first_response:
                continue

            delta_hours = (first_response.created_at - first_customer_at).total_seconds() / 3600
            if delta_hours >= 0:
                first_response_hours.append(delta_hours)

    sorted_response = sorted(first_response_hours)
    response_samples = len(sorted_response)
    avg_response = (sum(sorted_response) / response_samples) if response_samples else 0.0
    median_response = sorted_response[response_samples // 2] if response_samples else 0.0
    p95_response = sorted_response[int(0.95 * (response_samples - 1))] if response_samples else 0.0

    result = {
        "summary": {
            "threads_total": len(threads),
            "unread_threads": unread_total,
            "unread_rate": round((unread_total / len(threads) * 100), 2) if threads else 0.0,
            "first_response_samples": response_samples,
            "avg_first_response_hours": round(avg_response, 2),
            "median_first_response_hours": round(median_response, 2),
            "p95_first_response_hours": round(p95_response, 2),
        },
        "by_type": {
            key: {
                "threads": by_type_total[key],
                "unread": unread_by_type.get(key, 0),
            }
            for key in sorted(by_type_total.keys())
        },
    }

    payload = {
        "ok": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "filters": _format_filters(filters),
        "data": result,
        "errors": [],
        "meta": {
            "cache": "miss",
            "telemetry": {},
            "sources": ["db.threads", "db.messages"],
        },
    }
    _cache_set(cache_key, payload)

    endpoint = _endpoint_name(cache_key)
    response_ms = _record_telemetry(endpoint, "miss", started_at)
    payload["meta"]["telemetry"] = _telemetry_stats(endpoint, response_ms)
    return jsonify(payload)


@bp.route("/invoice-coverage")
@login_required
def stats_invoice_coverage():
    """KPI pokrycia faktur dla zamowien z want_invoice=true."""
    started_at = time.perf_counter()
    filters, err = _parse_filters()
    if err:
        return err

    cache_key = "invoice-coverage|" + _build_cache_key(filters)
    cached_payload = _cache_get(cache_key)
    if cached_payload is not None:
        endpoint = _endpoint_name(cache_key)
        response_ms = _record_telemetry(endpoint, "hit", started_at)
        cached = dict(cached_payload)
        cached["generated_at"] = datetime.now(timezone.utc).isoformat()
        cached["meta"] = dict(cached.get("meta") or {})
        cached["meta"]["cache"] = "hit"
        cached["meta"]["telemetry"] = _telemetry_stats(endpoint, response_ms)
        return jsonify(cached)

    start_ts = _to_ts(filters.date_from)
    end_ts = _to_ts(filters.date_to)

    with get_session() as db:
        orders = _fetch_orders(db, filters, start_ts, end_ts)
        requested_orders = [o for o in orders if bool(o.want_invoice)]
        invoiced_orders = [o for o in requested_orders if o.wfirma_invoice_id is not None]
        missing_orders = [o for o in requested_orders if o.wfirma_invoice_id is None]

        emailed_count = 0
        for order in invoiced_orders:
            flags: dict[str, bool] = {}
            if order.emails_sent:
                try:
                    parsed = json.loads(order.emails_sent)
                    if isinstance(parsed, dict):
                        flags = parsed
                except (TypeError, ValueError):
                    flags = {}
            if bool(flags.get("invoice")):
                emailed_count += 1

    requested_total = len(requested_orders)
    invoiced_total = len(invoiced_orders)
    missing_total = len(missing_orders)
    coverage_pct = (invoiced_total / requested_total * 100) if requested_total else 0.0
    email_coverage_pct = (emailed_count / requested_total * 100) if requested_total else 0.0

    result = {
        "summary": {
            "orders_total": len(orders),
            "requested_total": requested_total,
            "invoiced_total": invoiced_total,
            "missing_total": missing_total,
            "emailed_total": emailed_count,
            "coverage_pct": round(coverage_pct, 2),
            "email_coverage_pct": round(email_coverage_pct, 2),
        },
        "missing_orders": [
            {
                "order_id": order.order_id,
                "date_add": order.date_add,
                "platform": order.platform,
                "customer_name": order.customer_name,
            }
            for order in missing_orders[:50]
        ],
    }

    payload = {
        "ok": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "filters": _format_filters(filters),
        "data": result,
        "errors": [],
        "meta": {
            "cache": "miss",
            "telemetry": {},
            "sources": ["db.orders"],
        },
    }
    _cache_set(cache_key, payload)

    endpoint = _endpoint_name(cache_key)
    response_ms = _record_telemetry(endpoint, "miss", started_at)
    payload["meta"]["telemetry"] = _telemetry_stats(endpoint, response_ms)
    return jsonify(payload)
