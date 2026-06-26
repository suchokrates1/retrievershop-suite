"""API statystyk Allegro Ads Panel (dane z Sales Center)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from flask import jsonify, request

from ..db import get_session
from ..models.allegro_ads_panel import AllegroAdsSnapshot
from ..services.allegro_ads_panel.profit import (
    _ratio,
    compute_profit_by_offer,
    summarize_offer_profit,
)
from ..services.stats_support import json_error as _json_error

AGGREGATE_CAMPAIGN_NAME = "Wszystkie kampanie"
AGGREGATE_CHART_KEY = ""


def _serialize_chart_point(point) -> dict:
    return {
        "day": point.day.isoformat(),
        "clicks": point.clicks,
        "impressions": point.impressions,
        "cost": _decimal(point.cost),
        "sale_count": point.sale_count,
        "sale_value": _decimal(point.sale_value),
        "ctr": _decimal(point.ctr),
        "cpc": _decimal(point.cpc),
        "roi": _decimal(point.roi),
    }


def _charts_by_campaign(chart_points) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for point in sorted(chart_points, key=lambda p: (p.campaign_entity_id or "", p.day)):
        key = point.campaign_entity_id or AGGREGATE_CHART_KEY
        grouped.setdefault(key, []).append(_serialize_chart_point(point))
    return grouped


def _decimal(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def _profit_metrics(*, cost: Decimal | None, summary: dict) -> dict:
    real_profit = Decimal(str(summary.get("real_profit") or 0))
    real_revenue = Decimal(str(summary.get("real_revenue") or 0))
    ad_cost = Decimal(str(cost or 0))
    net_profit = real_profit - ad_cost
    return {
        "real_profit": _decimal(real_profit),
        "real_revenue": _decimal(real_revenue),
        "orders_matched": int(summary.get("orders_matched") or 0),
        "ad_cost": _decimal(ad_cost),
        "net_profit": _decimal(net_profit),
        "poas": _ratio(real_profit, ad_cost),
        "roas_real": _ratio(real_revenue, ad_cost),
    }


def _sold_item_metrics(
    *,
    item,
    campaign_cost: Decimal | None,
    campaign_sale_value: Decimal | None,
    offer_profit: dict,
) -> dict:
    quantity = max(int(item.quantity or 0), 0)
    item_cost_share = Decimal("0")
    if campaign_cost and campaign_sale_value and Decimal(str(campaign_sale_value)) > 0:
        item_cost_share = Decimal(str(campaign_cost)) * (
            Decimal(str(item.sale_value)) / Decimal(str(campaign_sale_value))
        )

    real_profit = Decimal(str(offer_profit.get("real_profit") or 0))
    real_revenue = Decimal(str(offer_profit.get("real_revenue") or 0))
    net_profit = real_profit - item_cost_share
    qty_divisor = quantity if quantity > 0 else 1
    ad_cost_per_unit = item_cost_share / qty_divisor
    real_profit_per_unit = real_profit / qty_divisor
    net_profit_per_unit = net_profit / qty_divisor

    return {
        "offer_id": item.offer_id,
        "offer_name": item.offer_name,
        "quantity": quantity,
        "sale_value": _decimal(item.sale_value),
        "ad_cost": _decimal(item_cost_share),
        "ad_cost_per_unit": _decimal(ad_cost_per_unit),
        "real_profit": _decimal(real_profit),
        "real_profit_per_unit": _decimal(real_profit_per_unit),
        "real_revenue": _decimal(real_revenue),
        "orders_matched": int(offer_profit.get("orders") or 0),
        "net_profit": _decimal(net_profit),
        "net_profit_per_unit": _decimal(net_profit_per_unit),
        "poas": _ratio(real_profit, item_cost_share),
        "roas_real": _ratio(real_revenue, item_cost_share),
    }


def stats_ads_panel_overview():
    snapshot_date_raw = (request.args.get("snapshot_date") or "").strip()
    with get_session() as db:
        query = db.query(AllegroAdsSnapshot)
        if snapshot_date_raw:
            try:
                snap_date = date.fromisoformat(snapshot_date_raw)
            except ValueError:
                return _json_error("INVALID_DATE", "Nieprawidlowy format snapshot_date (YYYY-MM-DD)", 400)
            snapshot = query.filter(AllegroAdsSnapshot.snapshot_date == snap_date).first()
        else:
            snapshot = query.order_by(
                AllegroAdsSnapshot.snapshot_date.desc(),
                AllegroAdsSnapshot.synced_at.desc(),
            ).first()

        if not snapshot:
            return jsonify(
                {
                    "data": None,
                    "meta": {
                        "source": "allegro.ads.panel",
                        "message": "Brak zsynchronizowanych danych Ads Panel. Uruchom synchronizacje.",
                    },
                }
            )

        db.refresh(snapshot)

        campaign_rows = [
            row for row in snapshot.campaigns if row.campaign_name != AGGREGATE_CAMPAIGN_NAME
        ]
        all_offer_ids = {
            item.offer_id
            for row in campaign_rows
            for item in row.sold_items
            if item.offer_id
        }
        profit_by_offer = compute_profit_by_offer(
            db,
            period_start=snapshot.period_start,
            period_end=snapshot.period_end,
            offer_ids=all_offer_ids,
        )

        campaigns = []
        ad_sales: list[dict] = []
        for row in sorted(snapshot.campaigns, key=lambda c: c.campaign_name.lower()):
            campaign_offer_ids = {item.offer_id for item in row.sold_items if item.offer_id}
            if row.campaign_name == AGGREGATE_CAMPAIGN_NAME:
                campaign_profit_rows = profit_by_offer
            else:
                campaign_profit_rows = {
                    offer_id: profit_by_offer.get(offer_id, {})
                    for offer_id in campaign_offer_ids
                }
            campaign_summary = summarize_offer_profit(campaign_profit_rows)
            campaign_profit = _profit_metrics(cost=row.cost, summary=campaign_summary)

            sold_items = []
            for item in sorted(row.sold_items, key=lambda i: i.sale_value, reverse=True):
                offer_profit = profit_by_offer.get(item.offer_id, {})
                item_metrics = _sold_item_metrics(
                    item=item,
                    campaign_cost=row.cost,
                    campaign_sale_value=row.sale_value,
                    offer_profit=offer_profit,
                )
                sold_items.append(item_metrics)
                if row.campaign_name != AGGREGATE_CAMPAIGN_NAME:
                    ad_sales.append(
                        {
                            "campaign_name": row.campaign_name,
                            "campaign_entity_id": row.campaign_entity_id,
                            **item_metrics,
                        }
                    )

            campaigns.append(
                {
                    "campaign_name": row.campaign_name,
                    "campaign_entity_id": row.campaign_entity_id,
                    "clicks": row.clicks,
                    "impressions": row.impressions,
                    "ctr": _decimal(row.ctr),
                    "cpc": _decimal(row.cpc),
                    "cost": _decimal(row.cost),
                    "roi": _decimal(row.roi),
                    "interest": row.interest,
                    "sale_count": row.sale_count,
                    "sale_value": _decimal(row.sale_value),
                    **campaign_profit,
                    "sold_items": sold_items,
                }
            )

        ad_sales.sort(
            key=lambda row: (
                row.get("net_profit") if row.get("net_profit") is not None else 0
            ),
            reverse=True,
        )

        chart_by_campaign = _charts_by_campaign(snapshot.chart_points)
        default_chart = chart_by_campaign.get(AGGREGATE_CHART_KEY, [])

        payload = {
            "snapshot_date": snapshot.snapshot_date.isoformat(),
            "synced_at": snapshot.synced_at.isoformat() if snapshot.synced_at else None,
            "period_start": snapshot.period_start.isoformat(),
            "period_end": snapshot.period_end.isoformat(),
            "marketplace_id": snapshot.marketplace_id,
            "status": snapshot.status,
            "error_message": snapshot.error_message,
            "campaigns": campaigns,
            "ad_sales": ad_sales,
            "chart": default_chart,
            "charts": chart_by_campaign,
        }

    return jsonify(
        {
            "data": payload,
            "meta": {
                "source": "allegro.ads.panel",
                "generated_at": datetime.utcnow().isoformat() + "Z",
            },
        }
    )


def stats_ads_panel_sync():
    from flask import current_app

    from ..allegro_ads_scheduler import run_allegro_ads_sync_now

    try:
        result = run_allegro_ads_sync_now(current_app._get_current_object())
    except Exception as exc:
        return _json_error("ADS_PANEL_SYNC_FAILED", str(exc), 502)
    return jsonify({"ok": True, "result": result})
