"""Sesja HTTP z cookies Chromium (CDP)."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

import requests
import websockets

from magazyn.services.allegro_price_scraper.cdp import cdp_json_request
from magazyn.services.allegro_price_scraper.config import CDP_HOST, CDP_PORT

logger = logging.getLogger(__name__)

SCOPE_RE = re.compile(r"/statistics/(?:detailed|chart)/campaigns/([^/?]+)")


async def _cdp_get_cookies(host: str, port: int) -> list[dict[str, Any]]:
    targets = cdp_json_request(host, port, "/json/list")
    target = next(
        (t for t in targets if t.get("type") == "page" and "salescenter.allegro.com" in (t.get("url") or "")),
        None,
    )
    if not target:
        target = next((t for t in targets if t.get("type") == "page"), None)
    if not target:
        raise RuntimeError("Brak otwartej karty Chromium (CDP)")

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

        await call("Network.enable")
        cookies_resp = await call(
            "Network.getCookies",
            {"urls": ["https://salescenter.allegro.com", "https://edge.salescenter.allegro.com"]},
        )
        perf_resp = await call(
            "Runtime.evaluate",
            {
                "expression": """
                (function() {
                  const urls = performance.getEntriesByType('resource').map(e => e.name);
                  const scope = urls.map(u => {
                    const m = u.match(/statistics\\/(?:detailed|chart)\\/campaigns\\/([^/?]+)/);
                    return m ? m[1] : null;
                  }).find(Boolean);
                  return { scope, pageUrl: location.href };
                })()
                """,
                "returnByValue": True,
            },
        )
        page_info = perf_resp.get("result", {}).get("result", {}).get("value", {})

    return cookies_resp.get("result", {}).get("cookies", []), page_info, target.get("url")


def build_requests_session(cookies: list[dict[str, Any]]) -> requests.Session:
    session = requests.Session()
    jar = requests.cookies.RequestsCookieJar()
    for cookie in cookies:
        jar.set(
            cookie["name"],
            cookie["value"],
            domain=cookie.get("domain"),
            path=cookie.get("path", "/"),
        )
    session.cookies = jar
    return session


def fetch_cdp_session(host: str | None = None, port: int | None = None) -> tuple[requests.Session, dict[str, Any]]:
    """Zwraca sesję requests z cookies Sales Center + metadane scope z CDP."""
    host = host or CDP_HOST
    port = port or CDP_PORT
    cookies, page_info, page_url = asyncio.run(_cdp_get_cookies(host, port))
    if not cookies:
        raise RuntimeError("Brak cookies sesji Sales Center w Chromium")
    session = build_requests_session(cookies)
    meta = dict(page_info or {})
    meta["page_url"] = page_url
    meta["cookie_count"] = len(cookies)
    return session, meta
