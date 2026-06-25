"""Konfiguracja scrapera cen Allegro."""

from __future__ import annotations

import os

# Chrome DevTools wymaga IP lub localhost w Host header - hostname (np. "price-checker-chrome")
# powoduje HTTP 500: "Host header is specified and is not an IP address or localhost."
CDP_HOST = os.environ.get("CDP_HOST", "192.168.31.5")
CDP_PORT = int(os.environ.get("CDP_PORT", "9223"))
# Osobny Chromium (np. konto prywatne, ceny brutto) tylko dla price check; Ads zostaje na CDP_PORT.
CDP_PORT_PRICE_CHECK = int(os.environ.get("CDP_PORT_PRICE_CHECK", str(CDP_PORT)))
MY_SELLER = "Retriever_Shop"
MAX_DELIVERY_DAYS = 3
# Standardowa stawka VAT dla konwersji cen netto (konto firmowe Allegro) -> brutto.
STANDARD_VAT_RATE = float(os.environ.get("ALLEGRO_VAT_RATE", "0.23"))
# Chromium wspoldzielony z Ads = konto firmowe; ceny w dialogu sa netto (czesto bez slowa "netto" w DOM).
COMPETITOR_PRICES_ARE_NET = os.environ.get("ALLEGRO_COMPETITOR_PRICES_ARE_NET", "true").lower() in {
    "1",
    "true",
    "yes",
}
# Przy bloku / braku dialogu: Google -> allegro.pl -> oferta (ludzka sciezka w CDP).
ENABLE_GOOGLE_WARMUP = os.environ.get("ALLEGRO_ENABLE_GOOGLE_WARMUP", "true").lower() in {
    "1",
    "true",
    "yes",
}
CDP_HTTP_TIMEOUT_SECONDS = 10
CDP_WS_TIMEOUT_SECONDS = 20
CDP_EVALUATE_TIMEOUT_SECONDS = 8
CDP_ARTICLE_POLL_ATTEMPTS = 20
CDP_ARTICLE_POLL_INTERVAL_SECONDS = 0.5