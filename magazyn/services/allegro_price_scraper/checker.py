"""Orkiestracja sprawdzania jednej oferty Allegro przez CDP."""

from __future__ import annotations

import asyncio
import logging
import random

try:
    import websockets
except ImportError:
    websockets = None
    logging.getLogger(__name__).warning("Brak pakietu websockets - scraping CDP niedostepny")

from .cdp import (
    cdp_call,
    close_page_target,
    create_isolated_page_target,
    detect_block_page,
    fetch_competitor_offer_payload,
    navigate_to_url,
    scroll_competitor_dialog,
    wait_for_dialog,
    warmup_via_google,
)
from .config import (
    CDP_ARTICLE_POLL_ATTEMPTS,
    CDP_ARTICLE_POLL_INTERVAL_SECONDS,
    CDP_HOST,
    CDP_HTTP_TIMEOUT_SECONDS,
    CDP_PORT,
    CDP_PORT_PRICE_CHECK,
    ENABLE_GOOGLE_WARMUP,
    MAX_DELIVERY_DAYS,
)
from .db import get_excluded_sellers
from .models import CompetitorOffer, PriceCheckResult
from .parser import build_offer_url, filter_competitor_offers, parse_competitor_articles

logger = logging.getLogger(__name__)


async def _poll_dialog_offers(ws, title: str) -> tuple[list[CompetitorOffer], dict, bool]:
    """Czeka na dialog, przewija i parsuje oferty konkurencji."""
    await scroll_competitor_dialog(ws)

    payload: dict = {
        "articleCount": 0,
        "articles": [],
        "containerSource": None,
        "dialogShowsNetPrices": False,
    }
    dialog_shows_net_prices = False
    fetch_msg_id = 200

    for _ in range(CDP_ARTICLE_POLL_ATTEMPTS):
        payload = await fetch_competitor_offer_payload(ws, msg_id=fetch_msg_id)
        fetch_msg_id += 1
        dialog_shows_net_prices = bool(payload.get("dialogShowsNetPrices"))
        offers = parse_competitor_articles(
            payload.get("articles", []),
            title,
            dialog_shows_net_prices=dialog_shows_net_prices,
        )
        if offers:
            return offers, payload, dialog_shows_net_prices
        if payload.get("articleCount", 0) > 0:
            await scroll_competitor_dialog(ws)
        await asyncio.sleep(CDP_ARTICLE_POLL_INTERVAL_SECONDS)

    return [], payload, dialog_shows_net_prices


async def _open_offer_page(ws, url: str, *, via_google: bool) -> bool:
    """Laduje strone oferty. Przy via_google najpierw warm-up przez wyszukiwarke."""
    if via_google and ENABLE_GOOGLE_WARMUP:
        await warmup_via_google(ws)
        await asyncio.sleep(random.uniform(1.5, 3.5))

    await navigate_to_url(ws, url)
    await asyncio.sleep(random.uniform(0.5, 1.5))

    blocked = await detect_block_page(ws)
    dialog_ok = await wait_for_dialog(ws)
    if blocked:
        logger.info("Wykryto blokade/captcha na stronie oferty")
    return dialog_ok and not blocked


async def check_offer_price(
    offer_id: str,
    title: str = "",
    my_price: float | None = None,
    cdp_host: str = CDP_HOST,
    cdp_port: int = CDP_PORT_PRICE_CHECK,
    max_delivery_days: int = MAX_DELIVERY_DAYS,
) -> PriceCheckResult:
    """Sprawdza ceny konkurencji dla danej oferty (tylko CDP, bez HTTP GET)."""
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

            loaded = await _open_offer_page(ws, url, via_google=False)
            if not loaded and ENABLE_GOOGLE_WARMUP:
                logger.info("Oferta %s: ponawiam przez Google (blok lub brak dialogu)", offer_id)
                result.source = "cdp_google"
                loaded = await _open_offer_page(ws, url, via_google=True)

            if not loaded:
                result.error = "Dialog 'Inne oferty produktu' nie pojawil sie"
                return result

            all_offers, payload, dialog_shows_net_prices = await _poll_dialog_offers(ws, title)

            logger.info(
                "Oferta %s: container=%s, raw_articles=%s, parsed_offers=%s, netto_dialog=%s",
                offer_id,
                payload.get("containerSource") or "brak",
                payload.get("articleCount", 0),
                len(all_offers),
                dialog_shows_net_prices,
            )

            if not all_offers:
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
                result.my_position = 1 + sum(
                    1 for competitor in competitors_filtered if competitor.price < result.my_price
                )
            elif result.my_price:
                result.my_position = 1

            result.success = True

    except Exception as exc:
        logger.error("Blad podczas sprawdzania oferty %s: %s", offer_id, exc)
        result.error = str(exc)
    finally:
        close_page_target(cdp_host, cdp_port, target_id)

    return result
