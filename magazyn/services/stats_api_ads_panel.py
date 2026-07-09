"""API statystyk Allegro Ads Panel (dane z Sales Center)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from flask import jsonify, request

from ..db import get_session
from ..models.allegro import AllegroOffer
from ..models.allegro_ads_panel import AllegroAdsSnapshot
from ..services.allegro_ads_panel.profit import (
    _ratio,
    compute_profit_by_offer,
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


def _scale_offer_profit_to_ads_sale(
    *,
    ads_sale_value: Decimal | None,
    offer_profit: dict,
) -> tuple[Decimal, Decimal, list[dict]]:
    """Skaluje zysk z zamówień do wartości sprzedaży atrybuowanej reklamie."""
    matched_revenue = Decimal(str(offer_profit.get("real_revenue") or 0))
    real_profit_raw = Decimal(str(offer_profit.get("real_profit") or 0))
    ads_value = Decimal(str(ads_sale_value or 0))

    if matched_revenue > 0 and ads_value > 0 and matched_revenue != ads_value:
        scale = ads_value / matched_revenue
        real_profit = real_profit_raw * scale
        real_revenue = ads_value
    elif ads_value > 0:
        real_profit = real_profit_raw
        real_revenue = ads_value
    else:
        real_profit = real_profit_raw
        real_revenue = matched_revenue

    order_lines = []
    for line in offer_profit.get("order_lines") or []:
        line_profit = Decimal(str(line.get("attributed_profit") or 0))
        line_revenue = Decimal(str(line.get("line_revenue") or 0))
        if matched_revenue > 0 and ads_value > 0 and matched_revenue != ads_value:
            line_profit *= scale
            line_revenue *= scale
        order_lines.append(
            {
                "order_id": line.get("order_id"),
                "quantity": int(line.get("quantity") or 0),
                "line_revenue": _decimal(line_revenue),
                "attributed_profit": _decimal(line_profit),
                "date_add": int(line.get("date_add") or 0),
            }
        )

    return real_profit, real_revenue, order_lines


def _sold_item_metrics(
    *,
    item,
    campaign_cost: Decimal | None,
    campaign_sale_value: Decimal | None,
    offer_profit: dict,
    product_id: int | None = None,
) -> dict:
    quantity = max(int(item.quantity or 0), 0)
    item_cost_share = Decimal("0")
    if campaign_cost and campaign_sale_value and Decimal(str(campaign_sale_value)) > 0:
        item_cost_share = Decimal(str(campaign_cost)) * (
            Decimal(str(item.sale_value)) / Decimal(str(campaign_sale_value))
        )

    real_profit, real_revenue, order_lines = _scale_offer_profit_to_ads_sale(
        ads_sale_value=item.sale_value,
        offer_profit=offer_profit,
    )
    net_profit = real_profit - item_cost_share
    qty_divisor = quantity if quantity > 0 else 1
    ad_cost_per_unit = item_cost_share / qty_divisor
    real_profit_per_unit = real_profit / qty_divisor
    net_profit_per_unit = net_profit / qty_divisor

    return {
        "offer_id": item.offer_id,
        "offer_name": item.offer_name,
        "product_id": product_id,
        "quantity": quantity,
        "sale_value": _decimal(item.sale_value),
        "ad_cost": _decimal(item_cost_share),
        "ad_cost_per_unit": _decimal(ad_cost_per_unit),
        "real_profit": _decimal(real_profit),
        "real_profit_per_unit": _decimal(real_profit_per_unit),
        "real_revenue": _decimal(real_revenue),
        "orders_matched": int(offer_profit.get("orders") or 0),
        "orders_in_period": len(order_lines),
        "net_profit": _decimal(net_profit),
        "net_profit_per_unit": _decimal(net_profit_per_unit),
        "poas": _ratio(real_profit, item_cost_share),
        "roas_real": _ratio(real_revenue, item_cost_share),
        "order_lines": order_lines,
    }


def _empty_profit_summary() -> dict[str, Decimal | int]:
    return {
        "real_profit": Decimal("0"),
        "real_revenue": Decimal("0"),
        "orders_matched": 0,
    }


def _add_profit_summaries(target: dict, source: dict) -> None:
    target["real_profit"] += Decimal(str(source.get("real_profit") or 0))
    target["real_revenue"] += Decimal(str(source.get("real_revenue") or 0))
    target["orders_matched"] += int(source.get("orders_matched") or 0)


def _serialize_campaign_row(
    row,
    *,
    profit_by_offer: dict,
    product_by_offer: dict,
    profit_summary: dict | None = None,
    collect_ad_sales: bool = False,
) -> tuple[dict, list[dict], dict]:
    sold_items: list[dict] = []
    campaign_summary = _empty_profit_summary()
    ad_sales_items: list[dict] = []

    for item in sorted(row.sold_items, key=lambda i: i.sale_value, reverse=True):
        offer_profit = profit_by_offer.get(item.offer_id, {})
        item_metrics = _sold_item_metrics(
            item=item,
            campaign_cost=row.cost,
            campaign_sale_value=row.sale_value,
            offer_profit=offer_profit,
            product_id=product_by_offer.get(item.offer_id),
        )
        sold_items.append(item_metrics)
        campaign_summary["real_profit"] += Decimal(str(item_metrics.get("real_profit") or 0))
        campaign_summary["real_revenue"] += Decimal(str(item_metrics.get("real_revenue") or 0))
        campaign_summary["orders_matched"] += int(item_metrics.get("orders_matched") or 0)
        if collect_ad_sales:
            ad_sales_items.append(
                {
                    "campaign_name": row.campaign_name,
                    "campaign_entity_id": row.campaign_entity_id,
                    **item_metrics,
                }
            )

    campaign_profit = _profit_metrics(
        cost=row.cost,
        summary=profit_summary if profit_summary is not None else campaign_summary,
    )

    payload = {
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
    return payload, ad_sales_items, campaign_summary


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
        product_by_offer = {
            row.offer_id: row.product_id
            for row in db.query(AllegroOffer.offer_id, AllegroOffer.product_id)
            .filter(AllegroOffer.offer_id.in_(all_offer_ids))
            .all()
            if row.product_id
        }

        campaigns = []
        ad_sales: list[dict] = []
        aggregate_profit_summary = _empty_profit_summary()
        detail_rows = [
            row for row in snapshot.campaigns if row.campaign_name != AGGREGATE_CAMPAIGN_NAME
        ]
        aggregate_row = next(
            (row for row in snapshot.campaigns if row.campaign_name == AGGREGATE_CAMPAIGN_NAME),
            None,
        )

        for row in sorted(detail_rows, key=lambda c: c.campaign_name.lower()):
            campaign_payload, ad_sales_items, campaign_summary = _serialize_campaign_row(
                row,
                profit_by_offer=profit_by_offer,
                product_by_offer=product_by_offer,
                collect_ad_sales=True,
            )
            campaigns.append(campaign_payload)
            ad_sales.extend(ad_sales_items)
            _add_profit_summaries(aggregate_profit_summary, campaign_summary)

        if aggregate_row is not None:
            campaign_payload, _, _ = _serialize_campaign_row(
                aggregate_row,
                profit_by_offer=profit_by_offer,
                product_by_offer=product_by_offer,
                profit_summary=aggregate_profit_summary,
                collect_ad_sales=False,
            )
            campaigns.append(campaign_payload)

        campaigns.sort(key=lambda campaign: campaign["campaign_name"].lower())

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
