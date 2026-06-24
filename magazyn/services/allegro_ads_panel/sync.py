"""Synchronizacja statystyk Allegro Ads Panel do bazy."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import websockets

from magazyn.db import get_session
from magazyn.models.allegro_ads_panel import (
    AllegroAdsCampaignDaily,
    AllegroAdsChartDaily,
    AllegroAdsSnapshot,
    AllegroAdsSoldItem,
)
from magazyn.services.allegro_price_scraper.cdp import cdp_json_request
from magazyn.services.allegro_price_scraper.config import CDP_HOST, CDP_PORT

from .client import AllegroAdsPanelClient
from .session import fetch_cdp_session

logger = logging.getLogger(__name__)

WARSAW = ZoneInfo("Europe/Warsaw")

DISCOVER_CAMPAIGNS_JS = r"""
(function() {
  const out = [];
  const buttons = Array.from(document.querySelectorAll('button')).filter(b => /^\d+$/.test((b.innerText||'').trim()));
  for (const btn of buttons) {
    const fiberKey = Object.keys(btn).find(k => k.startsWith('__reactFiber'));
    if (!fiberKey) continue;
    let entityId = null;
    let f = btn[fiberKey];
    for (let i = 0; i < 25 && f; i++) {
      const p = f.memoizedProps || f.pendingProps;
      if (p && p.entityId) { entityId = p.entityId; break; }
      f = f.return;
    }
    if (!entityId) continue;
    let row = btn.closest('tr');
    let name = null;
    if (row) {
      const prev = row.previousElementSibling;
      if (prev && (prev.innerText||'').trim() && !/^\d/.test((prev.innerText||'').trim())) {
        name = (prev.innerText||'').replace(/\s+/g,' ').trim();
      }
    }
    if (!name) {
      name = 'Kampania ' + (btn.innerText||'').trim();
    }
    out.push({ name, entityId, soldHint: (btn.innerText||'').trim() });
  }
  const seen = new Set();
  return out.filter(item => {
    const key = item.entityId;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
})()
"""

KNOWN_CAMPAIGNS = (
    {"name": "Wszystkie kampanie", "entity_id_b64": None, "campaign_name_filter": None},
    {"name": "Ads Express", "entity_id_b64": "MjcyNGZkODEtY2ZjZC00MTYyLTg5NmYtN2ZjZDNkYTRkMTQ5AA", "campaign_name_filter": "Ads Express"},
    {"name": "Bestsellery", "entity_id_b64": "MDBlNzhkNDAtMjAxMy00N2M1LWJhNGEtZDdlMWJkMTkzM2Q2AA", "campaign_name_filter": "Bestsellery"},
)
KNOWN_BY_ENTITY = {c["entity_id_b64"]: c for c in KNOWN_CAMPAIGNS if c.get("entity_id_b64")}


def _month_period(reference: date | None = None) -> tuple[date, date]:
    ref = reference or datetime.now(WARSAW).date()
    start = ref.replace(day=1)
    return start, ref


async def _discover_campaigns_cdp(host: str, port: int) -> list[dict[str, str | None]]:
    targets = cdp_json_request(host, port, "/json/list")
    target = next(
        (t for t in targets if t.get("type") == "page" and "salescenter.allegro.com/ads" in (t.get("url") or "")),
        None,
    )
    if not target:
        return [dict(x) for x in KNOWN_CAMPAIGNS]

    ws_url = (target.get("webSocketDebuggerUrl") or "").replace("localhost", host).replace("127.0.0.1", host)
    async with websockets.connect(ws_url, open_timeout=20) as ws:
        msg_id = 1

        async def call(method: str, params: dict | None = None) -> dict:
            nonlocal msg_id
            await ws.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
            cur = msg_id
            msg_id += 1
            while True:
                data = json.loads(await ws.recv())
                if data.get("id") == cur:
                    return data

        resp = await call("Runtime.evaluate", {"expression": DISCOVER_CAMPAIGNS_JS, "returnByValue": True})
        discovered = resp.get("result", {}).get("result", {}).get("value") or []

    campaigns = [dict(KNOWN_CAMPAIGNS[0])]
    discovered_entities: dict[str, str] = {}
    for item in discovered:
        entity_id = item.get("entityId")
        if entity_id:
            discovered_entities[entity_id] = item.get("name") or ""

    for known in KNOWN_CAMPAIGNS[1:]:
        entry = dict(known)
        if entry["entity_id_b64"] in discovered_entities:
            entry["entity_id_b64"] = entry["entity_id_b64"] or discovered_entities[entry["entity_id_b64"]]
        campaigns.append(entry)

    if len(campaigns) == 1:
        campaigns.extend(dict(x) for x in KNOWN_CAMPAIGNS[1:])
    return campaigns


def sync_ads_panel_statistics(
    *,
    snapshot_date: date | None = None,
    cdp_host: str | None = None,
    cdp_port: int | None = None,
) -> dict[str, Any]:
    """Pobiera dane z panelu Ads i zapisuje snapshot w bazie."""
    host = cdp_host or CDP_HOST
    port = cdp_port or CDP_PORT
    snap_date = snapshot_date or datetime.now(WARSAW).date()
    period_start, period_end = _month_period(snap_date)

    http_session, meta = fetch_cdp_session(host, port)
    scope_id = meta.get("scope")
    if not scope_id:
        scope_id = "NDc0MjA3MjAA"

    client = AllegroAdsPanelClient(http_session)
    campaigns = asyncio.run(_discover_campaigns_cdp(host, port))

    result: dict[str, Any] = {
        "snapshot_date": snap_date.isoformat(),
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "scope_id_b64": scope_id,
        "campaigns_synced": 0,
        "sold_items_synced": 0,
        "chart_points": 0,
    }

    with get_session() as db:
        existing = (
            db.query(AllegroAdsSnapshot)
            .filter(AllegroAdsSnapshot.snapshot_date == snap_date)
            .one_or_none()
        )
        if existing:
            db.delete(existing)
            db.flush()

        snapshot = AllegroAdsSnapshot(
            snapshot_date=snap_date,
            marketplace_id=client.marketplace_id,
            scope_id_b64=scope_id,
            period_start=period_start,
            period_end=period_end,
            status="ok",
        )
        db.add(snapshot)
        db.flush()

        try:
            chart_points = client.fetch_chart(
                scope_id,
                period_start=period_start,
                period_end=period_end,
                campaign_name=None,
            )
            for point in chart_points:
                db.add(
                    AllegroAdsChartDaily(
                        snapshot_id=snapshot.id,
                        day=point.day,
                        clicks=point.clicks,
                        impressions=point.impressions,
                        cost=point.cost,
                        sale_count=point.sale_count,
                        sale_value=point.sale_value,
                        ctr=point.ctr,
                        cpc=point.cpc,
                        roi=point.roi,
                    )
                )
            result["chart_points"] = len(chart_points)

            for campaign in campaigns:
                name = campaign["name"]
                entity_id = campaign.get("entity_id_b64")
                name_filter = campaign.get("campaign_name_filter")

                payload = client.fetch_campaign_summary(
                    scope_id,
                    period_start=period_start,
                    period_end=period_end,
                    campaign_name=name_filter,
                )
                summary = client.summary_from_payload(name, entity_id, payload)
                row = AllegroAdsCampaignDaily(
                    snapshot_id=snapshot.id,
                    campaign_entity_id=entity_id or f"summary:{name}",
                    campaign_name=summary.name,
                    clicks=summary.clicks,
                    impressions=summary.impressions,
                    ctr=summary.ctr,
                    cpc=summary.cpc,
                    cost=summary.cost,
                    roi=summary.roi,
                    interest=summary.interest,
                    sale_count=summary.sale_count,
                    sale_value=summary.sale_value,
                )
                db.add(row)
                db.flush()
                result["campaigns_synced"] += 1

                if entity_id and summary.sale_count > 0:
                    sold_items = client.fetch_sold_items(
                        scope_id,
                        entity_id_b64=entity_id,
                        period_start=period_start,
                        period_end=period_end,
                    )
                    for item in sold_items:
                        if not item.offer_id:
                            continue
                        db.add(
                            AllegroAdsSoldItem(
                                campaign_daily_id=row.id,
                                offer_id=item.offer_id,
                                offer_name=item.offer_name,
                                quantity=item.quantity,
                                sale_value=item.sale_value,
                            )
                        )
                        result["sold_items_synced"] += 1
        except Exception as exc:
            snapshot.status = "error"
            snapshot.error_message = str(exc)
            logger.exception("Allegro Ads panel sync failed: %s", exc)
            result["error"] = str(exc)
        db.commit()

    return result
