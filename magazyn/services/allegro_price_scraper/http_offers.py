"""Prototyp: pobieranie podsumowania cen konkurencji z HTML Allegro (SSR JSON)."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

import requests

from .config import MY_SELLER
from .parser import gross_from_net, normalize_seller_name, parse_price
from .session import fetch_allegro_session

logger = logging.getLogger(__name__)

SUMMARY_TITLE = "Ten produkt od innych sprzedających"
BUSINESS_OFFER_URL = "https://business.allegro.pl/oferta/x-{offer_id}"


@dataclass
class SsrCompetitorSummary:
    """Pojedyncza oferta z sekcji NAJTANIEJ / NAJSZYBCIEJ na stronie oferty."""

    label: str
    net_price: float | None
    gross_price: float | None
    price_label: str
    subtitle: str
    selector: str


@dataclass
class SsrOffersSnapshot:
    offer_id: str
    product_id: str | None
    product_name: str | None
    offer_count: int
    summaries: list[SsrCompetitorSummary]
    source_url: str
    edge_host: str | None = None


def _iter_json_script_blobs(html: str) -> list[dict[str, Any]]:
    blobs: list[dict[str, Any]] = []
    for match in re.finditer(r"<script[^>]*>(\{.*?\})</script>", html, re.DOTALL):
        text = match.group(1)
        if SUMMARY_TITLE not in text and "rawPrice" not in text:
            continue
        try:
            blobs.append(json.loads(text))
        except json.JSONDecodeError:
            continue
    return blobs


def _find_summary_block(obj: Any) -> dict[str, Any] | None:
    if isinstance(obj, dict):
        if obj.get("title") == SUMMARY_TITLE:
            return obj
        for value in obj.values():
            found = _find_summary_block(value)
            if found:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _find_summary_block(item)
            if found:
                return found
    return None


def _parse_price_block(raw_price: dict[str, Any] | None, secondary: dict[str, Any] | None) -> tuple[float | None, float | None, str]:
    if not raw_price:
        return None, None, ""

    label = str(raw_price.get("label") or "")
    net_price = None
    gross_price = None
    try:
        net_price = float(str(raw_price.get("amount", "")).replace(",", "."))
    except (TypeError, ValueError):
        net_price = None

    # secondaryPrice to autorytatywne brutto z Allegro:
    #   "231,00 zl z 23% VAT" -> jawne brutto
    #   "219,99 zl bez VAT"   -> sprzedawca zwolniony, brutto == netto
    if secondary:
        sec_label = str(secondary.get("label") or "").lower()
        main = str(secondary.get("main") or "")
        fraction = str(secondary.get("fraction") or "").replace("\u00a0", " ")
        combined = f"{main}{fraction}".strip()
        if "bez vat" in sec_label:
            gross_price = net_price
        elif combined and re.search(r"\bvat\b|%\s*vat", sec_label):
            try:
                gross_price = parse_price(combined)
            except ValueError:
                gross_price = None

    if gross_price is None and net_price is not None:
        gross_price = gross_from_net(net_price) if label.lower() == "netto" else net_price

    return net_price, gross_price, label


def _parse_summary_links(summary: dict[str, Any]) -> list[SsrCompetitorSummary]:
    parsed: list[SsrCompetitorSummary] = []
    for group in summary.get("links") or []:
        group_title = str(group.get("title") or "")
        for link in group.get("links") or []:
            net_price, gross_price, price_label = _parse_price_block(
                link.get("rawPrice"),
                link.get("secondaryPrice"),
            )
            parsed.append(
                SsrCompetitorSummary(
                    label=group_title,
                    net_price=net_price,
                    gross_price=gross_price,
                    price_label=price_label,
                    subtitle=str(link.get("subtitle") or ""),
                    selector=str(link.get("selector") or ""),
                )
            )
    return parsed


def _extract_edge_host(html: str) -> str | None:
    match = re.search(r'"edgeHost":"(https://[^"]+)"', html)
    return match.group(1) if match else None


def parse_offer_page_html(offer_id: str, html: str, *, source_url: str | None = None) -> SsrOffersSnapshot | None:
    """Parsuje wbudowany JSON z HTML strony oferty (business.allegro.pl)."""
    summary = None
    for blob in _iter_json_script_blobs(html):
        summary = _find_summary_block(blob)
        if summary:
            break

    if not summary:
        return None

    product_id = None
    match = re.search(r'"productId":"([a-f0-9-]{36})"', html)
    if match:
        product_id = match.group(1)

    return SsrOffersSnapshot(
        offer_id=offer_id,
        product_id=product_id,
        product_name=summary.get("productName"),
        offer_count=int(summary.get("offerCount") or 0),
        summaries=_parse_summary_links(summary),
        source_url=source_url or BUSINESS_OFFER_URL.format(offer_id=offer_id),
        edge_host=_extract_edge_host(html),
    )


def fetch_offer_ssr_snapshot(
    offer_id: str,
    session: requests.Session | None = None,
) -> SsrOffersSnapshot | None:
    """Pobiera strone oferty HTTP i zwraca podsumowanie cen konkurencji z SSR."""
    http = session or fetch_allegro_session()
    url = BUSINESS_OFFER_URL.format(offer_id=offer_id)
    response = http.get(url, timeout=25)
    if response.status_code != 200:
        logger.warning("SSR oferty %s: HTTP %s", offer_id, response.status_code)
        return None

    snapshot = parse_offer_page_html(offer_id, response.text, source_url=url)
    if snapshot:
        logger.info(
            "SSR oferty %s: %s konkurentow (podsumowanie %s pozycji), edge=%s",
            offer_id,
            snapshot.offer_count,
            len(snapshot.summaries),
            snapshot.edge_host,
        )
    return snapshot


def cheapest_gross_from_snapshot(snapshot: SsrOffersSnapshot) -> float | None:
    """Zwraca najnizsza cene brutto z podsumowania SSR (NAJTANIEJ / NAJSZYBCIEJ)."""
    prices = [item.gross_price for item in snapshot.summaries if item.gross_price is not None]
    return min(prices) if prices else None


__all__ = [
    "SsrCompetitorSummary",
    "SsrOffersSnapshot",
    "cheapest_gross_from_snapshot",
    "fetch_offer_ssr_snapshot",
    "parse_offer_page_html",
]
