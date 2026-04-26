"""Endpointy zwrotow API statystyk."""

from __future__ import annotations

from .stats_endpoint_context import (
    Decimal,
    Order,
    Return,
    ReturnStatusLog,
    _build_alerts,
    _build_cache_key,
    _cache_get,
    _cache_set,
    _endpoint_name,
    _fetch_orders,
    _format_filters,
    _is_cod,
    _parse_filters,
    _record_telemetry,
    _telemetry_stats,
    _to_ts,
    datetime,
    defaultdict,
    get_session,
    jsonify,
    time,
    timedelta,
    timezone,
)


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
