"""API statystyk (MVP v1)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
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
    AllegroPriceHistory,
    Order,
    OrderProduct,
    OrderStatusLog,
    PriceReportItem,
    Return,
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


def _format_filters(filters: StatsFilters) -> dict[str, str]:
    return {
        "date_from": filters.date_from.strftime("%Y-%m-%d"),
        "date_to": (filters.date_to - timedelta(days=1)).strftime("%Y-%m-%d"),
        "granularity": filters.granularity,
        "platform": filters.platform,
        "payment_type": filters.payment_type,
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
    type_name_map = {t.get("id"): t.get("description") or t.get("name") or t.get("id") for t in types_list if t.get("id")}

    agg: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for e in entries:
        t = (e.get("type") or {}).get("id") or "UNKNOWN"
        amount = Decimal(str((e.get("value") or {}).get("amount") or 0))
        if amount < 0:
            agg[t] += abs(amount)

    ads_result = get_period_ads_cost(access_token, date_from_iso, date_to_iso)
    ads_total = Decimal(str(ads_result.get("total_cost") or 0))

    with get_session() as db:
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
        for order_id, ship_started_at in ship_start.items():
            delivered_at = ship_end.get(order_id)
            if not delivered_at or delivered_at < ship_started_at:
                continue
            lead_times_hours.append((delivered_at - ship_started_at).total_seconds() / 3600)

        shipped_total = sum(1 for o in orders if o.delivery_package_nr)
        delivered_total = sum(1 for oid in ship_end.keys() if oid in orders_map)
        in_transit = max(shipped_total - delivered_total, 0)

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
