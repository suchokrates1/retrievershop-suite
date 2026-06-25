"""Orkiestracja sprawdzania jednej oferty Allegro przez CDP."""

from __future__ import annotations

import asyncio
import logging

try:
    import websockets
except ImportError:
    websockets = None
    logging.getLogger(__name__).warning("Brak pakietu websockets - scraping CDP niedostepny")

from .cdp import (
    cdp_call,
    close_page_target,
    create_isolated_page_target,
    fetch_competitor_offer_payload,
    navigate_to_url,
    wait_for_dialog,
)
from .config import (
    CDP_ARTICLE_POLL_ATTEMPTS,
    CDP_ARTICLE_POLL_INTERVAL_SECONDS,
    CDP_HOST,
    CDP_HTTP_TIMEOUT_SECONDS,
    CDP_PORT,
    CDP_PORT_PRICE_CHECK,
    MAX_DELIVERY_DAYS,
    PRICE_CHECK_HTTP_FALLBACK,
)
from .db import get_excluded_sellers
from .models import CompetitorOffer, PriceCheckResult
from .parser import build_offer_url, filter_competitor_offers, parse_competitor_articles

logger = logging.getLogger(__name__)


def _maybe_http_fallback(
    offer_id: str,
    my_price: float | None,
    cdp_host: str,
    cdp_port: int,
) -> PriceCheckResult | None:
    """Wywoluje fallback SSR tylko gdy wlaczony flaga konfiguracyjna."""
    if not PRICE_CHECK_HTTP_FALLBACK:
        return None
    return _http_ssr_fallback(offer_id, my_price, cdp_host, cdp_port)


def _http_ssr_fallback(
    offer_id: str,
    my_price: float | None,
    cdp_host: str,
    cdp_port: int,
) -> PriceCheckResult | None:
    """Fallback przez SSR HTTP gdy dialog CDP nie wstanie.

    Daje najtanszego konkurenta (brutto z VAT) i liczbe ofert z podsumowania
    Allegro. Pozycja jest przyblizona (SSR podaje tylko NAJTANIEJ/NAJSZYBCIEJ),
    dlatego wynik jest oznaczony jako zrodlo 'ssr'.
    """
    try:
        from .http_offers import cheapest_gross_from_snapshot, fetch_offer_ssr_snapshot
        from .session import fetch_allegro_session
    except Exception as exc:  # pragma: no cover - brak zaleznosci
        logger.debug("Fallback SSR niedostepny: %s", exc)
        return None

    try:
        snapshot = fetch_offer_ssr_snapshot(
            offer_id, session=fetch_allegro_session(cdp_host, cdp_port)
        )
    except Exception as exc:
        logger.warning("Fallback SSR oferty %s nie powiodl sie: %s", offer_id, exc)
        return None

    if not snapshot:
        return None

    cheapest_gross = cheapest_gross_from_snapshot(snapshot)
    if cheapest_gross is None:
        return None

    result = PriceCheckResult(offer_id=offer_id, success=True, my_price=my_price)
    result.source = "ssr"
    result.competitors_all_count = snapshot.offer_count
    cheapest = CompetitorOffer(
        seller="(SSR podsumowanie)",
        price=cheapest_gross,
        price_with_delivery=cheapest_gross,
        is_mine=False,
    )
    result.competitors = [cheapest]
    result.cheapest_competitor = cheapest
    if my_price:
        result.my_position = 1 if my_price <= cheapest_gross else 2
    logger.info(
        "Oferta %s: fallback SSR -> najtanszy konkurent %.2f zl brutto (%s ofert)",
        offer_id,
        cheapest_gross,
        snapshot.offer_count,
    )
    return result


async def check_offer_price(
    offer_id: str,
    title: str = "",
    my_price: float | None = None,
    cdp_host: str = CDP_HOST,
    cdp_port: int = CDP_PORT_PRICE_CHECK,
    max_delivery_days: int = MAX_DELIVERY_DAYS,
) -> PriceCheckResult:
    """Sprawdza ceny konkurencji dla danej oferty."""
    result = PriceCheckResult(
        offer_id=offer_id,
        success=False,
        my_price=my_price,
    )

    if websockets is None:
        result.error = "Brak pakietu websockets - zainstaluj: pip install websockets"
        return result

    url = build_offer_url(offer_id, title)
    target_id = None

    try:
        target_info = create_isolated_page_target(cdp_host, cdp_port)
        target_id = target_info.get("id")
        ws_url = target_info.get("webSocketDebuggerUrl")
        if not ws_url:
            raise RuntimeError("Chrome nie zwrocil webSocketDebuggerUrl dla nowej karty")
        logger.debug("CDP WebSocket: %s", ws_url)

        async with websockets.connect(
            ws_url,
            max_size=10 * 1024 * 1024,
            open_timeout=CDP_HTTP_TIMEOUT_SECONDS,
            ping_timeout=CDP_HTTP_TIMEOUT_SECONDS,
            close_timeout=5,
        ) as ws:
            await cdp_call(ws, "Emulation.setFocusEmulationEnabled", {"enabled": True}, msg_id=898)
            await cdp_call(ws, "Emulation.clearDeviceMetricsOverride", msg_id=899)

            await navigate_to_url(ws, url)
            if not await wait_for_dialog(ws):
                fallback = await asyncio.to_thread(
                    _maybe_http_fallback, offer_id, my_price, cdp_host, cdp_port
                )
                if fallback is not None:
                    return fallback
                result.error = "Dialog 'Inne oferty produktu' nie pojawil sie"
                return result

            payload = {"articleCount": 0, "articles": [], "containerSource": None, "dialogShowsNetPrices": False}
            all_offers = []
            fetch_msg_id = 200
            dialog_shows_net_prices = False
            for _ in range(CDP_ARTICLE_POLL_ATTEMPTS):
                payload = await fetch_competitor_offer_payload(ws, msg_id=fetch_msg_id)
                fetch_msg_id += 1
                dialog_shows_net_prices = bool(payload.get("dialogShowsNetPrices"))
                count = payload.get("articleCount", 0)
                all_offers = parse_competitor_articles(
                    payload.get("articles", []),
                    title,
                    dialog_shows_net_prices=dialog_shows_net_prices,
                )
                if all_offers:
                    logger.debug(
                        "Znaleziono %s artykulow i %s parsowalnych ofert w dialogu (%s)",
                        count,
                        len(all_offers),
                        payload.get("containerSource"),
                    )
                    break
                if count > 0:
                    logger.debug(
                        "Kontener %s ma %s artykulow, ale jeszcze brak parsowalnych ofert",
                        payload.get("containerSource") or "brak",
                        count,
                    )
                await asyncio.sleep(CDP_ARTICLE_POLL_INTERVAL_SECONDS)

            logger.info(
                "Oferta %s: container=%s, raw_articles=%s, parsed_offers=%s, netto_dialog=%s",
                offer_id,
                payload.get("containerSource") or "brak",
                payload.get("articleCount", 0),
                len(all_offers),
                dialog_shows_net_prices,
            )

            if not all_offers:
                fallback = await asyncio.to_thread(
                    _maybe_http_fallback, offer_id, my_price, cdp_host, cdp_port
                )
                if fallback is not None:
                    return fallback
                result.error = (
                    "Brak ofert w dialogu "
                    f"(container={payload.get('containerSource') or 'brak'}, "
                    f"raw_articles={payload.get('articleCount', 0)})"
                )
                return result

            result.our_other_offers = [offer for offer in all_offers if offer.is_mine]
            if result.our_other_offers:
                logger.info(
                    "Znaleziono %s naszych innych ofert w dialogu: %s",
                    len(result.our_other_offers),
                    ", ".join(offer.offer_id or "?" for offer in result.our_other_offers),
                )

            competitors_all = [offer for offer in all_offers if not offer.is_mine]
            result.competitors_all_count = len(competitors_all)
            competitors_filtered, filter_stats = filter_competitor_offers(
                competitors_all,
                get_excluded_sellers(),
                max_delivery_days,
            )

            if filter_stats["delivery"] > 0:
                logger.info(
                    "Odfiltrowano %s ofert z dostawa >= %s dni roboczych",
                    filter_stats["delivery"],
                    max_delivery_days,
                )
            if filter_stats["excluded_sellers"] > 0:
                logger.info("Odfiltrowano %s ofert od wykluczonych sprzedawcow", filter_stats["excluded_sellers"])
            if filter_stats["condition"] > 0:
                logger.info(
                    "Odfiltrowano %s ofert z nieobslugiwanym stanem (np. powystawowy/uzywany)",
                    filter_stats["condition"],
                )

            result.competitors = competitors_filtered
            if competitors_filtered:
                result.cheapest_competitor = min(competitors_filtered, key=lambda offer: offer.price)

            if result.my_price and competitors_filtered:
                result.my_position = 1 + sum(1 for competitor in competitors_filtered if competitor.price < result.my_price)
            elif result.my_price:
                result.my_position = 1

            result.success = True

    except Exception as exc:
        logger.error("Blad podczas sprawdzania oferty %s: %s", offer_id, exc)
        result.error = str(exc)
    finally:
        close_page_target(cdp_host, cdp_port, target_id)

    return result