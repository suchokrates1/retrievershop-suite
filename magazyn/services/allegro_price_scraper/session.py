"""Sesja HTTP Allegro (cookies z Chromium CDP)."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import requests
import websockets

from magazyn.services.allegro_ads_panel.session import build_requests_session
from magazyn.services.allegro_price_scraper.cdp import cdp_json_request
from magazyn.services.allegro_price_scraper.config import CDP_HOST, CDP_PORT

logger = logging.getLogger(__name__)

ALLEGRO_COOKIE_URLS = (
    "https://allegro.pl",
    "https://business.allegro.pl",
    "https://edge.allegro.pl",
    "https://edge.business.allegro.pl",
)


async def _cdp_get_allegro_cookies(host: str, port: int) -> list[dict[str, Any]]:
    targets = cdp_json_request(host, port, "/json/list")
    target = next((entry for entry in targets if entry.get("type") == "page"), None)
    if not target:
        raise RuntimeError("Brak otwartej karty Chromium (CDP)")

    ws_url = (target.get("webSocketDebuggerUrl") or "").replace("localhost", host).replace("127.0.0.1", host)
    async with websockets.connect(ws_url, open_timeout=20) as ws:
        await ws.send(
            json.dumps(
                {
                    "id": 1,
                    "method": "Network.getCookies",
                    "params": {"urls": list(ALLEGRO_COOKIE_URLS)},
                }
            )
        )
        while True:
            payload = json.loads(await ws.recv())
            if payload.get("id") == 1:
                return payload.get("result", {}).get("cookies", [])
    return []


def fetch_allegro_session(host: str | None = None, port: int | None = None) -> requests.Session:
    """Buduje requests.Session z cookies zalogowanej sesji Allegro z Chromium."""
    host = host or CDP_HOST
    port = port or CDP_PORT
    cookies = asyncio.run(_cdp_get_allegro_cookies(host, port))
    if not cookies:
        raise RuntimeError("Brak cookies sesji Allegro w Chromium")

    session = build_requests_session(cookies)
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "pl-PL,pl;q=0.9",
        }
    )
    logger.debug("Zaladowano %s cookies Allegro z CDP %s:%s", len(cookies), host, port)
    return session
