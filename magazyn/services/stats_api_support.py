"""Endpointy obslugi klienta i faktur API statystyk."""

from __future__ import annotations

from .stats_endpoint_context import (
    Message,
    Thread,
    _TELEMETRY,
    _build_cache_key,
    _cache_get,
    _cache_set,
    _endpoint_name,
    _fetch_orders,
    _format_filters,
    _parse_filters,
    _record_telemetry,
    _telemetry_stats,
    _to_ts,
    datetime,
    defaultdict,
    get_session,
    json,
    jsonify,
    time,
    timezone,
)


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
