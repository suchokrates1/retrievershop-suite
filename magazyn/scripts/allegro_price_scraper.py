#!/usr/bin/env python3
"""
Allegro Price Scraper using Oxylabs Web Unblocker
Extracts competitor prices from "Inne oferty produktu" section

Usage:
    python allegro_price_scraper.py <allegro_url>
    python allegro_price_scraper.py --test

Requirements:
    - requests
    - beautifulsoup4
"""

import requests
import re
import json
import sys
from bs4 import BeautifulSoup
from typing import Dict, List, Optional
from dataclasses import dataclass
from urllib.parse import urlparse

# Oxylabs Web Unblocker credentials
OXYLABS_PROXY = "https://unblock.oxylabs.io:60000"
OXYLABS_USER = "suchokrates1_B9Mtv"
OXYLABS_PASS = "S+vhqka1b=oSW0"


@dataclass
class CompetitorOffer:
    """Competitor offer data"""
    seller_name: str
    price: float
    delivery_days: Optional[int]
    offer_url: Optional[str]
    is_smart: bool = False


@dataclass
class ScrapingResult:
    """Result of scraping operation"""
    success: bool
    offer_id: str
    product_name: str
    main_price: Optional[float]
    main_seller: Optional[str]
    competitors: List[CompetitorOffer]
    error: Optional[str] = None


def fetch_allegro_page(url: str, timeout: int = 180) -> Optional[str]:
    """
    Fetch Allegro page through Oxylabs Web Unblocker
    
    Args:
        url: Allegro offer URL
        timeout: Request timeout in seconds
        
    Returns:
        HTML content or None on failure
    """
    proxies = {
        "http": f"http://{OXYLABS_USER}:{OXYLABS_PASS}@unblock.oxylabs.io:60000",
        "https": f"http://{OXYLABS_USER}:{OXYLABS_PASS}@unblock.oxylabs.io:60000",
    }
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8",
    }
    
    try:
        print(f"Fetching: {url}")
        response = requests.get(
            url,
            proxies=proxies,
            headers=headers,
            timeout=timeout,
            verify=False  # Oxylabs uses its own cert
        )
        
        if response.status_code == 200:
            print(f"Success! Content length: {len(response.text)} bytes")
            return response.text
        else:
            print(f"Error: HTTP {response.status_code}")
            return None
            
    except requests.exceptions.Timeout:
        print("Error: Request timeout")
        return None
    except Exception as e:
        print(f"Error: {e}")
        return None


def extract_offer_id(url: str) -> str:
    """Extract offer ID from Allegro URL"""
    # URL format: https://allegro.pl/oferta/...-OFFER_ID
    match = re.search(r'-(\d+)(?:\?|$)', url)
    if match:
        return match.group(1)
    return ""


def parse_price(price_str: str) -> Optional[float]:
    """Parse Polish price format (123,45 zł) to float"""
    if not price_str:
        return None
    # Remove currency and whitespace
    clean = re.sub(r'[^\d,.]', '', price_str)
    # Convert comma to dot
    clean = clean.replace(',', '.')
    try:
        return float(clean)
    except ValueError:
        return None


def extract_delivery_days(delivery_text: str) -> Optional[int]:
    """
    Extract delivery days from text like "dostawa w poniedziałek" or "dostawa za 7-14 dni"
    Returns None if it's a fast delivery (Polish seller), or days if it's slow (Chinese seller)
    """
    if not delivery_text:
        return None
        
    text = delivery_text.lower()
    
    # Quick delivery keywords (Polish sellers)
    quick_keywords = ['dziś', 'jutro', 'pojutrze', 'poniedziałek', 'wtorek', 'środa', 
                      'czwartek', 'piątek', 'sobota', 'niedziela']
    
    for kw in quick_keywords:
        if kw in text:
            return 1  # Quick delivery
    
    # Check for "za X-Y dni" pattern (slow delivery, likely Chinese)
    match = re.search(r'za\s*(\d+)\s*[-–]\s*(\d+)\s*dni', text)
    if match:
        return int(match.group(2))  # Return max days
        
    match = re.search(r'za\s*(\d+)\s*dni', text)
    if match:
        return int(match.group(1))
        
    return None


def parse_competitor_offers(html: str) -> List[CompetitorOffer]:
    """
    Parse "Inne oferty produktu" section from HTML
    
    This section contains competitor offers for the same product.
    """
    competitors = []
    soup = BeautifulSoup(html, 'html.parser')
    
    # Method 1: Look for JSON data in script tags
    scripts = soup.find_all('script')
    for script in scripts:
        if script.string and 'Inne oferty produktu' in script.string:
            # Try to extract JSON data
            try:
                # Find JSON objects in script
                json_matches = re.findall(r'\{[^{}]*"title"\s*:\s*"Inne oferty produktu"[^{}]*\}', script.string)
                for json_str in json_matches:
                    print(f"Found JSON with 'Inne oferty produktu': {json_str[:200]}...")
            except:
                pass
    
    # Method 2: Look for aria-label with prices
    price_elements = soup.find_all(attrs={"aria-label": re.compile(r'\d+[,\.]\d+\s*zł', re.IGNORECASE)})
    print(f"Found {len(price_elements)} elements with price aria-labels")
    
    for elem in price_elements:
        aria = elem.get('aria-label', '')
        price = parse_price(aria)
        if price:
            print(f"  Price from aria-label: {price} zł")
    
    # Method 3: Look for specific price container classes
    # Allegro uses classes like "mli8_k4" for prices
    price_spans = soup.find_all('span', class_=re.compile(r'mli8_k4|mgn2_21'))
    
    # Method 4: Search for seller links in "other offers" section
    # Look for data-analytics attributes with offer IDs
    offer_tiles = soup.find_all(attrs={"data-role": "offer-tile"})
    print(f"Found {len(offer_tiles)} offer tiles")
    
    # Method 5: Parse from __NEXT_DATA__ or similar JSON blob
    next_data = soup.find('script', id='__NEXT_DATA__')
    if next_data and next_data.string:
        try:
            data = json.loads(next_data.string)
            # Navigate through the JSON to find offers
            print("Found __NEXT_DATA__, searching for competitor data...")
        except json.JSONDecodeError:
            pass
    
    # Method 6: Look for productOtherOffers section
    other_offers_section = soup.find(attrs={"data-box-name": re.compile(r'productOtherOffers', re.IGNORECASE)})
    if other_offers_section:
        print("Found productOtherOffers section!")
        # Extract prices and sellers from this section
        # Look for price patterns
        section_text = other_offers_section.get_text()
        prices = re.findall(r'(\d{2,3})[,.](\d{2})\s*zł', section_text)
        for p in prices:
            price = float(f"{p[0]}.{p[1]}")
            print(f"  Found price in section: {price} zł")
    
    return competitors


def parse_main_offer(html: str) -> tuple:
    """
    Extract main offer price and seller from HTML
    
    Returns:
        (price, seller_name)
    """
    soup = BeautifulSoup(html, 'html.parser')
    
    price = None
    seller = None
    
    # Find main price - usually in a prominent span with specific classes
    # Look for "data-analytics-category" = "allegro.price"
    price_container = soup.find(attrs={"data-analytics-category": "allegro.price"})
    if price_container:
        price_text = price_container.get_text()
        price = parse_price(price_text)
    
    # Alternative: find by aria-label on buy button
    buy_button = soup.find(attrs={"data-role": "buy-button"})
    if buy_button:
        aria = buy_button.get('aria-label', '')
        if 'zł' in aria:
            price = parse_price(aria)
    
    # Find seller name
    seller_match = re.search(r'"sellerName"\s*:\s*"([^"]+)"', html)
    if seller_match:
        seller = seller_match.group(1)
    
    # Alternative: look for seller link
    seller_link = soup.find('a', attrs={"data-analytics-click-label": re.compile(r'seller', re.IGNORECASE)})
    if seller_link:
        seller = seller_link.get_text(strip=True)
    
    return price, seller


def scrape_allegro_offer(url: str) -> ScrapingResult:
    """
    Main function to scrape Allegro offer and extract competitor prices
    
    Args:
        url: Allegro offer URL
        
    Returns:
        ScrapingResult with all extracted data
    """
    offer_id = extract_offer_id(url)
    
    # Fetch HTML
    html = fetch_allegro_page(url)
    if not html:
        return ScrapingResult(
            success=False,
            offer_id=offer_id,
            product_name="",
            main_price=None,
            main_seller=None,
            competitors=[],
            error="Failed to fetch page"
        )
    
    # Check for DataDome block
    if 'captcha-delivery.com' in html or 'DataDome' in html:
        return ScrapingResult(
            success=False,
            offer_id=offer_id,
            product_name="",
            main_price=None,
            main_seller=None,
            competitors=[],
            error="Blocked by DataDome"
        )
    
    # Parse main offer
    main_price, main_seller = parse_main_offer(html)
    
    # Extract product name from title
    soup = BeautifulSoup(html, 'html.parser')
    title_tag = soup.find('title')
    product_name = title_tag.get_text() if title_tag else ""
    # Clean up title
    product_name = re.sub(r'\s*•.*$', '', product_name)
    product_name = re.sub(r'\s*\(\d+\)\s*$', '', product_name)
    
    # Parse competitor offers
    competitors = parse_competitor_offers(html)
    
    return ScrapingResult(
        success=True,
        offer_id=offer_id,
        product_name=product_name.strip(),
        main_price=main_price,
        main_seller=main_seller,
        competitors=competitors
    )


def test_scraper():
    """Test the scraper with a sample URL"""
    test_url = "https://allegro.pl/oferta/szelki-dla-psa-truelove-front-line-premium-xl-granatowe-18180401323"
    
    print("=" * 60)
    print("ALLEGRO PRICE SCRAPER TEST")
    print("=" * 60)
    print()
    
    result = scrape_allegro_offer(test_url)
    
    print()
    print("=" * 60)
    print("RESULTS:")
    print("=" * 60)
    print(f"Success: {result.success}")
    print(f"Offer ID: {result.offer_id}")
    print(f"Product: {result.product_name}")
    print(f"Main Price: {result.main_price} zł")
    print(f"Main Seller: {result.main_seller}")
    print(f"Competitors: {len(result.competitors)}")
    
    if result.competitors:
        print()
        print("Competitor offers:")
        for comp in result.competitors:
            print(f"  - {comp.seller_name}: {comp.price} zł (delivery: {comp.delivery_days} days)")
    
    if result.error:
        print(f"Error: {result.error}")
    
    return result


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings('ignore', message='Unverified HTTPS request')
    
    if len(sys.argv) > 1:
        if sys.argv[1] == "--test":
            test_scraper()
        else:
            url = sys.argv[1]
            result = scrape_allegro_offer(url)
            print(json.dumps({
                "success": result.success,
                "offer_id": result.offer_id,
                "product_name": result.product_name,
                "main_price": result.main_price,
                "main_seller": result.main_seller,
                "competitors": [
                    {
                        "seller": c.seller_name,
                        "price": c.price,
                        "delivery_days": c.delivery_days
                    } for c in result.competitors
                ],
                "error": result.error
            }, indent=2, ensure_ascii=False))
    else:
        print("Usage:")
        print("  python allegro_price_scraper.py <allegro_url>")
        print("  python allegro_price_scraper.py --test")
