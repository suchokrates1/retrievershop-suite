"""Allegro scraper using Camoufox for anti-detection.

Camoufox is better at bypassing DataDome than regular Selenium.
Saves bandwidth by blocking images and unnecessary resources.
"""

from __future__ import annotations

import logging
import os
import re
import time
import random
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Callable, List, Optional, Tuple

logger = logging.getLogger(__name__)

try:
    from camoufox.sync_api import Camoufox
except ImportError:
    Camoufox = None  # type: ignore


@dataclass(slots=True)
class Offer:
    """Representation of a competitor offer scraped from Allegro."""
    title: str
    price: str
    seller: str
    url: str


def _log_step(logs: Optional[List[str]], message: str) -> None:
    """Record a scraping step both in-memory and in application logs."""
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug("[Camoufox] %s", message)
    if logs is not None:
        logs.append(message)


def _extract_price(text: str) -> str:
    """Extract price string from text containing 'zł'."""
    if not text:
        return ""
    match = re.search(r"[\d\s]+[,.]?\d*\s*zł", text, re.IGNORECASE)
    if match:
        return match.group(0).strip()
    return text.strip()


def parse_price_amount(price_str: str) -> Optional[Decimal]:
    """Parse price string like '123,45 zł' to Decimal."""
    if not price_str:
        return None
    cleaned = re.sub(r"[^\d,.]", "", price_str)
    cleaned = cleaned.replace(",", ".")
    try:
        return Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return None


def fetch_competitors_camoufox(
    product_url: str,
    *,
    stop_seller: Optional[str] = None,
    limit: int = 30,
    headless: bool = True,
    block_images: bool = True,
    proxy: Optional[str] = None,
    log_callback: Optional[Callable[[str], None]] = None,
) -> Tuple[List[Offer], List[str]]:
    """Fetch competitor offers using Camoufox (anti-detection browser).
    
    Parameters
    ----------
    product_url : str
        Full Allegro offer URL
    stop_seller : str, optional
        Stop when reaching this seller (usually your own store)
    limit : int
        Maximum offers to fetch
    headless : bool
        Run browser in headless mode
    block_images : bool
        Block images to save bandwidth (recommended)
    proxy : str, optional
        Proxy URL (format: http://user:pass@host:port)
    log_callback : callable, optional
        Callback for logging steps
        
    Returns
    -------
    tuple
        (list of Offer, list of log messages)
    """
    if Camoufox is None:
        raise RuntimeError(
            "Camoufox is required for this scraper. "
            "Install with: pip install camoufox && camoufox fetch"
        )
    
    logs: List[str] = []
    offers: List[Offer] = []
    
    # Get proxy from env if not provided
    if proxy is None:
        proxy = os.environ.get("ALLEGRO_PROXY_URL") or os.environ.get("HTTP_PROXY")
    
    _log_step(logs, f"Starting Camoufox scraper for {product_url}")
    _log_step(logs, f"Headless: {headless}, Block images: {block_images}")
    if proxy:
        _log_step(logs, f"Using proxy: {proxy[:30]}...")
    
    try:
        # Camoufox options
        camoufox_opts = {
            "headless": headless,
            "humanize": True,  # Human-like mouse movements
        }
        
        if proxy:
            camoufox_opts["proxy"] = {"server": proxy}
        
        with Camoufox(**camoufox_opts) as browser:
            page = browser.new_page()
            
            # Block images and media to save bandwidth
            if block_images:
                def route_handler(route):
                    if route.request.resource_type in ["image", "media", "font", "stylesheet"]:
                        route.abort()
                    else:
                        route.continue_()
                
                page.route("**/*", route_handler)
                _log_step(logs, "Blocking images/media/fonts to save bandwidth")
            
            # Navigate to product page
            _log_step(logs, "Navigating to product page...")
            page.goto(product_url, timeout=60000)
            page.wait_for_timeout(3000 + random.randint(0, 2000))
            
            title = page.title()
            _log_step(logs, f"Page title: {title}")
            
            # Check for DataDome/captcha - but only if it's actually blocking
            content = page.content()
            
            # DataDome shows a minimal page with just captcha
            # Real product page has longer title with product name
            is_blocked = (
                # Page title is just "allegro.pl" without product info
                title.strip().lower() == "allegro.pl"
                # Or page has captcha-delivery iframe AND very short content
                or ("geo.captcha-delivery.com" in content and len(content) < 10000)
            )
            
            if is_blocked:
                _log_step(logs, "DataDome captcha blocking detected!")
                raise RuntimeError("DataDome anti-bot captcha detected")
            
            _log_step(logs, "Product page loaded successfully")
            
            # Look for "Other offers" / "Inne oferty" link
            _log_step(logs, "Looking for competitor offers section...")
            
            # Try to find and click the "Najtańsze" or "Inne oferty" link
            selectors = [
                "a[href='#inne-oferty-produktu']",
                "[data-cy='product-offers-link']",
                "a:has-text('Najtańsze')",
                "a:has-text('Inne oferty')",
                "a:has-text('WSZYSTKIE OFERTY')",
                "text=inne oferty produktu",
            ]
            
            clicked = False
            for selector in selectors:
                try:
                    link = page.query_selector(selector)
                    if link and link.is_visible():
                        link.scroll_into_view_if_needed()
                        page.wait_for_timeout(500)
                        link.click()
                        clicked = True
                        _log_step(logs, f"Clicked offers link: {selector}")
                        break
                except Exception as e:
                    continue
            
            if not clicked:
                _log_step(logs, "No 'Other offers' link found - may be single seller")
                return [], logs
            
            # Wait for offers section to load
            page.wait_for_timeout(2000 + random.randint(0, 1000))
            
            # Scroll to offers section
            try:
                section = page.query_selector("#inne-oferty-produktu")
                if section:
                    section.scroll_into_view_if_needed()
            except Exception:
                pass
            
            page.wait_for_timeout(1000)
            
            # Find offer rows
            offer_selectors = [
                "[data-role='offer']",
                "[data-testid='offer-card']",
                "[data-analytics-view-custom-context='PRODUCT_OFFERS_LISTING'] article",
                "#inne-oferty-produktu article",
                "#inne-oferty-produktu [data-box-name='listing-item']",
            ]
            
            rows = []
            for selector in offer_selectors:
                rows = page.query_selector_all(selector)
                if rows:
                    _log_step(logs, f"Found {len(rows)} offer rows with: {selector}")
                    break
            
            if not rows:
                _log_step(logs, "No offer rows found in listing")
                return [], logs
            
            seen_urls: set = set()
            
            for row in rows:
                try:
                    # Scroll row into view
                    row.scroll_into_view_if_needed()
                    page.wait_for_timeout(100)
                    
                    # Find offer link
                    anchor = row.query_selector("a[href*='/oferta/']")
                    if not anchor:
                        continue
                    
                    href = anchor.get_attribute("href") or ""
                    if not href or "/oferta/" not in href:
                        continue
                    
                    # Normalize URL
                    if href.startswith("//"):
                        href = f"https:{href}"
                    elif href.startswith("/"):
                        href = f"https://allegro.pl{href}"
                    
                    if href in seen_urls:
                        continue
                    seen_urls.add(href)
                    
                    # Get title
                    offer_title = anchor.inner_text().strip() or "(brak tytułu)"
                    
                    # Get price
                    price_text = ""
                    price_selectors = [
                        "[data-role='price']",
                        "[data-testid='price']",
                        "[class*='price']",
                        "span:has-text('zł')",
                    ]
                    for ps in price_selectors:
                        try:
                            price_el = row.query_selector(ps)
                            if price_el:
                                price_text = price_el.inner_text().strip()
                                if price_text:
                                    break
                        except Exception:
                            continue
                    
                    price = _extract_price(price_text)
                    
                    # Get seller
                    seller_text = ""
                    seller_selectors = [
                        "[data-role='seller-name']",
                        "[data-testid='seller-name']",
                        "a[href*='/uzytkownik/']",
                        "a[href*='/strefa_sprzedawcy/']",
                    ]
                    for ss in seller_selectors:
                        try:
                            seller_el = row.query_selector(ss)
                            if seller_el:
                                seller_text = seller_el.inner_text().strip()
                                if seller_text:
                                    break
                        except Exception:
                            continue
                    
                    # Clean seller name
                    seller_clean = re.sub(r"\s*Poleca.*$", "", seller_text).strip()
                    seller_clean = re.sub(r"\s+Firma.*$", "", seller_clean).strip()
                    seller_clean = re.sub(r"\s+Oficjalny sklep.*$", "", seller_clean).strip()
                    
                    # Stop at our own seller
                    if stop_seller and seller_clean.lower() == stop_seller.lower():
                        _log_step(logs, f"Reached own seller: {seller_clean}, stopping")
                        break
                    
                    offers.append(Offer(
                        title=offer_title[:100],
                        price=price,
                        seller=seller_clean or seller_text,
                        url=href,
                    ))
                    
                    _log_step(logs, f"Found: {price} - {seller_clean or '?'}")
                    
                    if len(offers) >= limit:
                        _log_step(logs, f"Reached limit of {limit} offers")
                        break
                        
                except Exception as e:
                    _log_step(logs, f"Error parsing row: {e}")
                    continue
            
            _log_step(logs, f"Total offers found: {len(offers)}")
            
    except Exception as e:
        _log_step(logs, f"Scraper error: {e}")
        raise RuntimeError(f"Camoufox scraper failed: {e}") from e
    
    return offers, logs


def fetch_competitors_for_offer_camoufox(
    offer_id: str,
    *,
    stop_seller: Optional[str] = None,
    limit: int = 30,
    headless: bool = True,
    block_images: bool = True,
    proxy: Optional[str] = None,
    log_callback: Optional[Callable[[str], None]] = None,
) -> Tuple[List[Offer], List[str]]:
    """Convenience wrapper using offer ID instead of full URL."""
    product_url = f"https://allegro.pl/oferta/{offer_id}"
    return fetch_competitors_camoufox(
        product_url,
        stop_seller=stop_seller,
        limit=limit,
        headless=headless,
        block_images=block_images,
        proxy=proxy,
        log_callback=log_callback,
    )


__all__ = [
    "Offer",
    "fetch_competitors_camoufox",
    "fetch_competitors_for_offer_camoufox",
    "parse_price_amount",
]
