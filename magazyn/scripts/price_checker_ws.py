#!/usr/bin/env python3
"""Kompatybilny punkt wejscia dla scrapera cen Allegro przez CDP."""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

# Pozwala uruchamiac plik bezposrednio jako skrypt z katalogu repo.
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from magazyn.services.allegro_price_scraper.cdp import (  # noqa: E402
    cdp_call,
    cdp_json_request as _cdp_json_request,
    close_page_target,
    create_isolated_page_target,
    extract_competitor_offers,
    extract_page_price,
    fetch_competitor_offer_payload,
    navigate_to_url,
    wait_for_dialog,
)
from magazyn.services.allegro_price_scraper.checker import check_offer_price  # noqa: E402
from magazyn.services.allegro_price_scraper.cli import check_offers_from_db, main, print_result  # noqa: E402
from magazyn.services.allegro_price_scraper.config import (  # noqa: E402
    CDP_ARTICLE_POLL_ATTEMPTS,
    CDP_ARTICLE_POLL_INTERVAL_SECONDS,
    CDP_EVALUATE_TIMEOUT_SECONDS,
    CDP_HOST,
    CDP_HTTP_TIMEOUT_SECONDS,
    CDP_PORT,
    CDP_PORT_PRICE_CHECK,
    CDP_WS_TIMEOUT_SECONDS,
    MAX_DELIVERY_DAYS,
    MY_SELLER,
)
from magazyn.services.allegro_price_scraper.db import (  # noqa: E402
    ensure_runtime_db_configured,
    get_excluded_sellers,
    reload_excluded_sellers,
)
from magazyn.services.allegro_price_scraper.delivery import (  # noqa: E402
    POLISH_MONTHS,
    _business_days_between,
    _easter_date,
    _polish_holidays,
    parse_delivery_days,
)
from magazyn.services.allegro_price_scraper.models import CompetitorOffer, PriceCheckResult  # noqa: E402
from magazyn.services.allegro_price_scraper.parser import (  # noqa: E402
    build_offer_url,
    detect_offer_condition,
    filter_competitor_offers,
    is_excluded_offer_condition,
    normalize_seller_name as _normalize_seller_name,
    parse_competitor_articles,
    parse_price,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

__all__ = [
    "CDP_ARTICLE_POLL_ATTEMPTS",
    "CDP_ARTICLE_POLL_INTERVAL_SECONDS",
    "CDP_EVALUATE_TIMEOUT_SECONDS",
    "CDP_HOST",
    "CDP_HTTP_TIMEOUT_SECONDS",
    "CDP_PORT",
    "CDP_PORT_PRICE_CHECK",
    "CDP_WS_TIMEOUT_SECONDS",
    "CompetitorOffer",
    "MAX_DELIVERY_DAYS",
    "MY_SELLER",
    "POLISH_MONTHS",
    "PriceCheckResult",
    "_business_days_between",
    "_cdp_json_request",
    "_easter_date",
    "_normalize_seller_name",
    "_polish_holidays",
    "build_offer_url",
    "cdp_call",
    "check_offer_price",
    "check_offers_from_db",
    "close_page_target",
    "create_isolated_page_target",
    "detect_offer_condition",
    "ensure_runtime_db_configured",
    "extract_competitor_offers",
    "extract_page_price",
    "fetch_competitor_offer_payload",
    "filter_competitor_offers",
    "get_excluded_sellers",
    "is_excluded_offer_condition",
    "main",
    "navigate_to_url",
    "parse_competitor_articles",
    "parse_delivery_days",
    "parse_price",
    "print_result",
    "reload_excluded_sellers",
    "wait_for_dialog",
]


if __name__ == "__main__":
    asyncio.run(main())