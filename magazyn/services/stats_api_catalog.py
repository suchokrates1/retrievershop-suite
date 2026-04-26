"""Endpointy katalogu, konkurencji i publikacji ofert API statystyk."""

from __future__ import annotations

from .stats_endpoint_context import (
    AllegroOffer,
    AllegroPriceHistory,
    Order,
    OrderProduct,
    PriceReportItem,
    _build_cache_key,
    _cache_get,
    _cache_set,
    _endpoint_name,
    _export_table,
    _fetch_orders,
    _format_filters,
    _json_error,
    _parse_filters,
    _record_telemetry,
    _telemetry_stats,
    _to_ts,
    case,
    datetime,
    defaultdict,
    func,
    get_session,
    jsonify,
    or_,
    request,
    time,
    timezone,
)


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
