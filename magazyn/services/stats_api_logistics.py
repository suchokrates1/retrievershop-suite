"""Endpointy operacyjne i logistyczne API statystyk."""

from __future__ import annotations

from .stats_endpoint_context import (
    OrderStatusLog,
    _build_alerts,
    _build_cache_key,
    _cache_get,
    _cache_set,
    _carrier_label,
    _delivery_method_label,
    _endpoint_name,
    _fetch_orders,
    _format_filters,
    _group_logistics_rows,
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
        first_status_by_order: dict[str, dict[str, datetime]] = defaultdict(dict)

        for log in logs:
            status = (log.status or "").strip().lower()
            status_counts[status] += 1
            if status not in first_status_by_order[log.order_id]:
                first_status_by_order[log.order_id][status] = log.timestamp
            if status in start_statuses and log.order_id not in ship_start:
                ship_start[log.order_id] = log.timestamp
            if status in end_statuses:
                ship_end[log.order_id] = log.timestamp

        transition_definitions = [
            ("wydrukowano", "spakowano"),
            ("spakowano", "wyslano"),
            ("wyslano", "w_transporcie"),
            ("wyslano", "dostarczono"),
        ]
        transition_samples: dict[str, list[float]] = defaultdict(list)
        for status_map in first_status_by_order.values():
            for source_status, target_status in transition_definitions:
                source_ts = status_map.get(source_status)
                target_ts = status_map.get(target_status)
                if not source_ts or not target_ts or target_ts < source_ts:
                    continue
                transition_key = f"{source_status}_to_{target_status}"
                delta_hours = (target_ts - source_ts).total_seconds() / 3600
                transition_samples[transition_key].append(delta_hours)

        status_transitions: list[dict[str, float | int | str]] = []
        for source_status, target_status in transition_definitions:
            transition_key = f"{source_status}_to_{target_status}"
            samples = sorted(transition_samples.get(transition_key, []))
            count = len(samples)
            if count == 0:
                status_transitions.append(
                    {
                        "transition": transition_key,
                        "count": 0,
                        "avg_hours": 0.0,
                        "median_hours": 0.0,
                        "p95_hours": 0.0,
                    }
                )
                continue
            avg_hours = sum(samples) / count
            median_hours = samples[count // 2]
            p95_hours = samples[int(0.95 * (count - 1))]
            status_transitions.append(
                {
                    "transition": transition_key,
                    "count": count,
                    "avg_hours": round(avg_hours, 2),
                    "median_hours": round(median_hours, 2),
                    "p95_hours": round(p95_hours, 2),
                }
            )

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
            "status_transitions": status_transitions,
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


def stats_order_funnel():
    """Funnel analizy dla zamowien - czasy przejscia miedzy statusami na podstawie raw events.
    
    Zwraca:
    - funnel: lista etapow z kontami i czasami srednich przejsc
    - transitions: szczegoly czasow przejsc BOUGHT -> FILLED_IN -> READY_FOR_PROCESSING
    - summary: statystyki ogolne (total_orders, avg_time_to_ready, etc.)
    """
    from ..models import OrderEvent
    
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


def stats_shipment_errors():
    """Shipment errors KPI - błędy przy generowaniu etykiet i tworzeniu przesyłek.
    
    Zwraca:
    - by_error_type: Liczba błędów per typ (label_generation_failed, invalid_address, etc.)
    - by_delivery_method: Liczba błędów per metoda dostawy (inpost, dhl, orlen, etc.)
    - unresolved: Liczba nierozwiązanych błędów
    - unresolved_by_type: Nierozwiązane błędy grouped by type
    """
    from ..models import ShipmentError
    
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
