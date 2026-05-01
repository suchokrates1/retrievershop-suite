"""Operacje Chrome DevTools Protocol dla scrapera Allegro."""

from __future__ import annotations

import asyncio
import json
import logging
import urllib.request
from typing import Any, Optional

from .config import CDP_EVALUATE_TIMEOUT_SECONDS, CDP_HTTP_TIMEOUT_SECONDS, CDP_WS_TIMEOUT_SECONDS
from .models import CompetitorOffer
from .parser import parse_competitor_articles

logger = logging.getLogger(__name__)


def cdp_json_request(host: str, port: int, path: str, method: str = "GET") -> dict[str, Any]:
    """Wykonuje zapytanie do HTTP JSON API Chrome DevTools."""
    if not path.startswith("/") or "://" in path:
        raise ValueError("Nieprawidlowa sciezka CDP")
    url = f"http://{host}:{port}{path}"
    request = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(request, timeout=CDP_HTTP_TIMEOUT_SECONDS) as response:  # nosec B310
        payload = response.read()
    return json.loads(payload) if payload else {}


def create_isolated_page_target(host: str, port: int) -> dict[str, Any]:
    """Tworzy nowa karte w Chrome i zwraca jej target CDP."""
    return cdp_json_request(host, port, "/json/new?about:blank", method="PUT")


def close_page_target(host: str, port: int, target_id: str | None) -> None:
    """Zamyka tymczasowa karte CDP."""
    if not target_id:
        return
    try:
        url = f"http://{host}:{port}/json/close/{target_id}"
        request = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(request, timeout=10):  # nosec B310
            pass
    except Exception as exc:
        logger.warning("Nie udalo sie zamknac targetu CDP %s: %s", target_id, exc)


async def cdp_call(
    ws,
    method: str,
    params: dict | None = None,
    msg_id: int = 1,
    timeout: float = CDP_WS_TIMEOUT_SECONDS,
) -> dict:
    """Wykonuje wywolanie CDP i zwraca wynik."""
    request = {"id": msg_id, "method": method}
    if params:
        request["params"] = params

    await ws.send(json.dumps(request))

    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            raise TimeoutError(f"Timeout CDP dla {method} po {timeout}s")

        try:
            response = await asyncio.wait_for(ws.recv(), timeout=remaining)
        except asyncio.TimeoutError as exc:
            raise TimeoutError(f"Timeout CDP dla {method} po {timeout}s") from exc
        data = json.loads(response)
        if data.get("id") == msg_id:
            if data.get("error"):
                error = data["error"]
                message = error.get("message") if isinstance(error, dict) else str(error)
                raise RuntimeError(f"CDP {method}: {message}")
            return data


async def navigate_to_url(ws, url: str, timeout: int = 30) -> None:
    """Nawiguje do podanego URL i czeka na zaladowanie."""
    logger.info("Nawiguje do: %s...", url[:80])

    await cdp_call(ws, "Page.enable", msg_id=1)
    await cdp_call(ws, "Page.navigate", {"url": url}, msg_id=2)

    start = asyncio.get_event_loop().time()
    while asyncio.get_event_loop().time() - start < timeout:
        try:
            message = await asyncio.wait_for(ws.recv(), timeout=1)
            data = json.loads(message)
            if data.get("method") == "Page.loadEventFired":
                logger.debug("Strona zaladowana")
                break
        except asyncio.TimeoutError:
            continue

    await asyncio.sleep(3)


async def wait_for_dialog(ws, timeout: int = 15) -> bool:
    """Czeka az pojawi sie dialog z ofertami."""
    js_check = '''
    (function() {
        const dialogs = document.querySelectorAll("[role='dialog']");
        for (const d of dialogs) {
            if (d.innerText?.includes("Inne oferty produktu")) {
                return true;
            }
        }
        return false;
    })()
    '''

    msg_id = 100
    start = asyncio.get_event_loop().time()
    while asyncio.get_event_loop().time() - start < timeout:
        result = await cdp_call(
            ws,
            "Runtime.evaluate",
            {"expression": js_check, "returnByValue": True},
            msg_id=msg_id,
            timeout=CDP_EVALUATE_TIMEOUT_SECONDS,
        )
        msg_id += 1
        if result.get("result", {}).get("result", {}).get("value"):
            logger.debug("Dialog znaleziony")
            return True
        await asyncio.sleep(1)
    return False


async def extract_page_price(ws) -> Optional[float]:
    """Wyciaga cene oferty ze strony."""
    js_code = '''
    (function() {
        const ariaPrice = document.querySelector('[aria-label*="cena z"]');
        if (ariaPrice) {
            const match = ariaPrice.getAttribute('aria-label').match(/(\\d+[,.]\\d{2})/);
            if (match) return match[1].replace(',', '.');
        }
        const metaPrice = document.querySelector('meta[property="product:price:amount"]');
        if (metaPrice) return metaPrice.content;
        const priceEl = document.querySelector('[data-testid="price"]');
        if (priceEl) {
            const match = priceEl.innerText.match(/(\\d+[,.]\\d{2})/);
            if (match) return match[1].replace(',', '.');
        }
        return null;
    })()
    '''
    result = await cdp_call(
        ws,
        "Runtime.evaluate",
        {"expression": js_code, "returnByValue": True},
        msg_id=50,
        timeout=CDP_EVALUATE_TIMEOUT_SECONDS,
    )
    value = result.get("result", {}).get("result", {}).get("value")
    if value:
        try:
            return float(str(value).replace(",", ".").replace(" ", ""))
        except (ValueError, TypeError):
            pass
    return None


async def fetch_competitor_offer_payload(ws, msg_id: int = 200) -> dict[str, Any]:
    """Pobiera surowe artykuly ofert z aktywnego dialogu produktowego."""
    js_code = r'''
    (function() {
        let container = null;
        let containerSource = null;

        const containerSelectors = [
            '[data-box-name="ProductOffersListingContainer"]',
            '[data-role="opbox-offers-list"]',
            '[data-testid*="offer"]',
            '[data-testid*="Offer"]',
            '[class*="offers-list"]',
            '[class*="offer-list"]',
            '[class*="ProductOffers"]'
        ];

        const hasOfferText = (candidate) => /zł|zl/i.test(candidate.innerText || '');
        const candidateKey = (candidate) => candidate.dataset?.boxName
            || candidate.dataset?.role
            || candidate.dataset?.testid
            || candidate.className
            || candidate.tagName;

        function pickContainer(root) {
            const seen = new Set();
            const candidates = [];

            function addCandidate(candidate, source) {
                if (!candidate || seen.has(candidate)) return;
                seen.add(candidate);
                const articleCount = candidate.querySelectorAll('article').length;
                if (articleCount > 0 && hasOfferText(candidate)) {
                    candidates.push({ candidate, source, articleCount });
                }
            }

            addCandidate(root, 'root');
            for (const selector of containerSelectors) {
                root.querySelectorAll(selector).forEach((candidate) => addCandidate(candidate, selector));
            }
            root.querySelectorAll('article').forEach((article) => addCandidate(article.parentElement, 'article-parent'));

            candidates.sort((left, right) => right.articleCount - left.articleCount);
            return candidates[0] || null;
        }

        const dialogs = Array.from(document.querySelectorAll("[role='dialog']"));
        const activeDialog = dialogs.find((dialog) => dialog.innerText?.includes("Inne oferty produktu"));

        if (activeDialog) {
            const picked = pickContainer(activeDialog);
            if (picked) {
                container = picked.candidate;
                containerSource = `dialog:${picked.source}:${candidateKey(container)}`;
            }
        }

        if (!container) {
            const picked = pickContainer(document.body);
            if (picked) {
                container = picked.candidate;
                containerSource = `visible-fallback:${picked.source}:${candidateKey(container)}`;
            }
        }

        if (!container) {
            return { containerSource: null, articleCount: 0, articles: [] };
        }

        const articles = container.querySelectorAll('article');
        return {
            containerSource,
            articleCount: articles.length,
            articles: Array.from(articles).map((art, idx) => {
                let offerId = null;
                let offerUrl = null;

                const produktLink = art.querySelector('a[href*="/produkt/"]');
                if (produktLink) {
                    const match = produktLink.href.match(/offerId=(\d+)/);
                    if (match) offerId = match[1];
                }

                if (!offerId) {
                    const ofertaLink = art.querySelector('a[href*="/oferta/"]');
                    if (ofertaLink) {
                        const match = ofertaLink.href.match(/\/oferta\/[^?#]*?-(\d{8,})/);
                        if (match) {
                            offerId = match[1];
                            offerUrl = ofertaLink.href;
                        }
                    }
                }

                if (!offerId) {
                    const allLinks = art.querySelectorAll('a[href]');
                    for (const link of allLinks) {
                        const match = link.href.match(/offerId=(\d+)/);
                        if (match) {
                            offerId = match[1];
                            break;
                        }
                    }
                }

                if (!offerId) {
                    const eventLink = art.querySelector('a[href*="/events/clicks"]');
                    if (eventLink) {
                        const redirectMatch = eventLink.href.match(/redirect=([^&]+)/);
                        if (redirectMatch) {
                            const decoded = decodeURIComponent(redirectMatch[1]);
                            const paramMatch = decoded.match(/offerId=(\d+)/);
                            if (paramMatch) {
                                offerId = paramMatch[1];
                            } else {
                                const slugMatch = decoded.match(/\/oferta\/[^?#]*?-(\d{8,})/);
                                if (slugMatch) offerId = slugMatch[1];
                            }
                            offerUrl = decoded;
                        }
                    }
                }

                let ariaPrice = null;
                const priceEl = art.querySelector('p[aria-label*="aktualna cena"]');
                if (priceEl) {
                    const match = priceEl.getAttribute('aria-label').match(/([\d\s]+(?:,\d{2})?)\s*zł/);
                    if (match) ariaPrice = match[1].replace(/\s/g, '');
                }

                return {
                    index: idx,
                    offerId: offerId,
                    offerUrl: offerUrl,
                    ariaPrice: ariaPrice,
                    text: art.innerText || ''
                };
            })
        };
    })()
    '''

    result = await cdp_call(
        ws,
        "Runtime.evaluate",
        {"expression": js_code, "returnByValue": True},
        msg_id=msg_id,
        timeout=CDP_EVALUATE_TIMEOUT_SECONDS,
    )

    return result.get("result", {}).get("result", {}).get("value", {}) or {
        "containerSource": None,
        "articleCount": 0,
        "articles": [],
    }


async def extract_competitor_offers(ws, product_title: str = "") -> list[CompetitorOffer]:
    """Wyciaga i parsuje oferty konkurencji z aktywnego dialogu."""
    payload = await fetch_competitor_offer_payload(ws)
    articles = payload.get("articles", [])

    if not articles:
        logger.warning("Nie znaleziono artykulow w dialogu")
        return []

    logger.info(
        "Pobrano %s artykulow z kontenera %s",
        payload.get("articleCount", len(articles)),
        payload.get("containerSource") or "brak",
    )
    return parse_competitor_articles(articles, product_title)