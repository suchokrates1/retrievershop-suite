"""Endpointy sprzedazowo-finansowe API statystyk."""

from __future__ import annotations

from .stats_endpoint_context import (
    AllegroOffer,
    Decimal,
    FinancialCalculator,
    OrderProduct,
    Return,
    _bucket_key,
    _build_cache_key,
    _cache_get,
    _cache_set,
    _endpoint_name,
    _export_table,
    _fetch_orders,
    _format_filters,
    _is_cod,
    _json_error,
    _order_products_map,
    _order_revenue,
    _parse_filters,
    _pct_change,
    _period_offsets,
    _record_telemetry,
    _telemetry_stats,
    _to_ts,
    _upsert_billing_types,
    datetime,
    defaultdict,
    func,
    get_session,
    jsonify,
    logger,
    request,
    settings_store,
    time,
    timedelta,
    timezone,
)


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


def stats_profit():
    started_at = time.perf_counter()
    trace_label = f"stats-profit:{int(time.time() * 1000)}"
    logger.info("Stats profit start: trace=%s args=%s", trace_label, dict(request.args))
    filters, err = _parse_filters()
    if err:
        logger.warning("Stats profit invalid filters: trace=%s", trace_label)
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
        logger.info(
            "Stats profit cache hit: trace=%s cache_key=%s response_ms=%.1f",
            trace_label,
            cache_key,
            response_ms,
        )
        return jsonify(cached)

    with get_session() as db:
        data_load_started_at = time.perf_counter()
        orders = _fetch_orders(db, filters, int(filters.date_from.timestamp()), int(filters.date_to.timestamp()))
        order_ids = [o.order_id for o in orders]
        products_map = _order_products_map(db, order_ids)
        prev_start, prev_end = int((filters.date_from - (filters.date_to - filters.date_from)).timestamp()), int(filters.date_from.timestamp())
        prev_orders = _fetch_orders(db, filters, prev_start, prev_end)
        prev_products = _order_products_map(db, [o.order_id for o in prev_orders])
        logger.info(
            "Stats profit db inputs loaded: trace=%s current_orders=%s prev_orders=%s current_order_products=%s prev_order_products=%s elapsed_ms=%.1f",
            trace_label,
            len(orders),
            len(prev_orders),
            len(products_map),
            len(prev_products),
            (time.perf_counter() - data_load_started_at) * 1000,
        )

    current_revenue = sum((_order_revenue(o, products_map) for o in orders), Decimal("0"))
    prev_revenue = sum((_order_revenue(o, prev_products) for o in prev_orders), Decimal("0"))

    access_token = settings_store.get("ALLEGRO_ACCESS_TOKEN")
    with get_session() as db2:
        calculator = FinancialCalculator(db2, settings_store)
        summary = calculator.get_period_summary(
            int(filters.date_from.timestamp()),
            int(filters.date_to.timestamp()),
            access_token=access_token,
            trace_label=trace_label,
        )

    net_profit_cur = Decimal(str(summary.net_profit))

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
    logger.info(
        "Stats profit done: trace=%s response_ms=%.1f revenue=%s net_profit=%s waterfall_steps=%s",
        trace_label,
        response_ms,
        current_revenue,
        net_profit_cur,
        len(waterfall),
    )
    return jsonify(payload)


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

    from ..allegro_api import fetch_billing_entries, fetch_billing_types, get_period_ads_cost

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

    from ..allegro_api import fetch_billing_entries

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
