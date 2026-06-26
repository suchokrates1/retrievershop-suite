"""Klient wewnętrznego API panelu Allegro Ads (edge.salescenter)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

import requests

BASE_URL = "https://edge.salescenter.allegro.com/ads-panel"
DEFAULT_MARKETPLACE = "allegro-pl"

EMPTY_FILTERS = {
    "campaignId": None,
    "campaignName": None,
    "campaignType": None,
    "adGroupId": None,
    "adGroupName": None,
    "inventoryUnitName": None,
    "offerIds": None,
}


@dataclass(frozen=True)
class CampaignSummary:
    name: str
    entity_id_b64: str | None
    clicks: int
    impressions: int
    ctr: Decimal | None
    cpc: Decimal | None
    cost: Decimal
    roi: Decimal | None
    interest: int
    sale_count: int
    sale_value: Decimal


@dataclass(frozen=True)
class SoldItem:
    offer_id: str
    offer_name: str
    quantity: int
    sale_value: Decimal


@dataclass(frozen=True)
class ChartPoint:
    day: date
    clicks: int
    impressions: int
    cost: Decimal
    sale_count: int
    sale_value: Decimal
    ctr: Decimal | None
    cpc: Decimal | None
    roi: Decimal | None


def _dec(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value))


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


class AllegroAdsPanelClient:
    def __init__(self, session: requests.Session, *, marketplace_id: str = DEFAULT_MARKETPLACE):
        self._session = session
        self.marketplace_id = marketplace_id
        self._headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Origin": "https://salescenter.allegro.com",
            "Referer": f"https://salescenter.allegro.com/ads/panel/stats/ads?marketplaceId={marketplace_id}",
            "X-PPC-OPERATING-MARKETPLACE": marketplace_id,
        }

    def _headers_for(self, *, include_marketplace_header: bool = True) -> dict[str, str]:
        if include_marketplace_header:
            return self._headers
        return {
            key: value
            for key, value in self._headers.items()
            if key != "X-PPC-OPERATING-MARKETPLACE"
        }

    def _post(
        self,
        path: str,
        body: dict,
        *,
        params: dict | None = None,
        include_marketplace_header: bool = True,
    ) -> dict:
        response = self._session.post(
            f"{BASE_URL}{path}",
            headers=self._headers_for(include_marketplace_header=include_marketplace_header),
            json=body,
            params=params,
            timeout=45,
        )
        response.raise_for_status()
        return response.json()

    def _table_body(
        self,
        *,
        period_start: date,
        period_end: date,
        campaign_name: str | None = None,
    ) -> dict:
        filters = dict(EMPTY_FILTERS)
        if campaign_name:
            filters["campaignName"] = campaign_name
        return {
            "startDate": period_start.isoformat(),
            "endDate": period_end.isoformat(),
            "granularity": "DAY",
            "filters": filters,
            "breakdown": "NONE",
            "sort": {"column": "NAME", "order": "ASC"},
            "page": {"page": 0, "size": 50},
        }

    def fetch_campaign_summary(
        self,
        scope_id_b64: str,
        *,
        period_start: date,
        period_end: date,
        campaign_name: str | None = None,
    ) -> dict:
        return self._post(
            f"/api/statistics/detailed/campaigns/{scope_id_b64}",
            self._table_body(period_start=period_start, period_end=period_end, campaign_name=campaign_name),
        )

    def fetch_chart(
        self,
        scope_id_b64: str,
        *,
        period_start: date,
        period_end: date,
        campaign_name: str | None = None,
    ) -> list[ChartPoint]:
        # Chart API returns all-zero series when X-PPC-OPERATING-MARKETPLACE is sent.
        payload = self._post(
            f"/api/v2/statistics/chart/campaigns/{scope_id_b64}",
            self._table_body(period_start=period_start, period_end=period_end, campaign_name=campaign_name),
            params={"marketplace": self.marketplace_id},
            include_marketplace_header=False,
        )
        points: list[ChartPoint] = []
        for item in payload.get("chart") or []:
            period = item.get("period") or {}
            values = item.get("values") or {}
            day_raw = period.get("startDate") or period.get("endDate")
            if not day_raw:
                continue
            points.append(
                ChartPoint(
                    day=date.fromisoformat(day_raw[:10]),
                    clicks=_int(values.get("clicks")),
                    impressions=_int(values.get("views")),
                    cost=_dec(values.get("cost")) or Decimal("0"),
                    sale_count=_int(values.get("totalAttributionCount")),
                    sale_value=_dec(values.get("totalAttributionValue")) or Decimal("0"),
                    ctr=_dec(values.get("ctr")),
                    cpc=_dec(values.get("cpc")),
                    roi=_dec(values.get("roi")),
                )
            )
        return points

    def fetch_sold_items(
        self,
        scope_id_b64: str,
        *,
        entity_id_b64: str,
        period_start: date,
        period_end: date,
    ) -> list[SoldItem]:
        payload = self._post(
            f"/api/statistics/detailed/sales/{scope_id_b64}",
            {
                "id": entity_id_b64,
                "dataType": "CAMPAIGN",
                "startDate": period_start.isoformat(),
                "endDate": period_end.isoformat(),
            },
        )
        items: list[SoldItem] = []
        for row in payload.get("salesStatistics") or []:
            items.append(
                SoldItem(
                    offer_id=str(row.get("offerId") or ""),
                    offer_name=str(row.get("offerName") or ""),
                    quantity=_int(row.get("count")),
                    sale_value=_dec(row.get("value")) or Decimal("0"),
                )
            )
        return items

    def summary_from_payload(self, name: str, entity_id_b64: str | None, payload: dict) -> CampaignSummary:
        summary = payload.get("summary") or {}
        return CampaignSummary(
            name=name,
            entity_id_b64=entity_id_b64,
            clicks=_int(summary.get("clicks")),
            impressions=_int(summary.get("impressions")),
            ctr=_dec(summary.get("ctr")),
            cpc=_dec(summary.get("cpc")),
            cost=_dec(summary.get("cost")) or Decimal("0"),
            roi=_dec(summary.get("roi")),
            interest=_int(summary.get("interest")),
            sale_count=_int(summary.get("saleCount")),
            sale_value=_dec(summary.get("saleValue")) or Decimal("0"),
        )
