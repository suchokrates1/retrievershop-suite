"""Konfiguracja scrapera cen Allegro."""

from __future__ import annotations

import os

# Chrome DevTools wymaga IP lub localhost w Host header - hostname (np. "price-checker-chrome")
# powoduje HTTP 500: "Host header is specified and is not an IP address or localhost."
CDP_HOST = os.environ.get("CDP_HOST", "192.168.31.5")
CDP_PORT = int(os.environ.get("CDP_PORT", "9223"))
MY_SELLER = "Retriever_Shop"
MAX_DELIVERY_DAYS = 3
CDP_HTTP_TIMEOUT_SECONDS = 10
CDP_WS_TIMEOUT_SECONDS = 20
CDP_EVALUATE_TIMEOUT_SECONDS = 8
CDP_ARTICLE_POLL_ATTEMPTS = 20
CDP_ARTICLE_POLL_INTERVAL_SECONDS = 0.5