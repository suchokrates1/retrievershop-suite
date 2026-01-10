#!/usr/bin/env python3
"""
Allegro Competitor Price Scraper using Browserless.io BrowserQL
Scrapes competitor prices from Allegro product offer pages.

Usage:
    python allegro_competitor_scraper.py <offer_url>
    python allegro_competitor_scraper.py --test
"""

import requests
import json
import re
import argparse
from bs4 import BeautifulSoup
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from datetime import datetime


# Browserless.io configuration
BROWSERLESS_TOKEN = "2TlFTbxoi626KAue012cce364011c0e7d24a364eed6e9f6ae"
BROWSERLESS_ENDPOINT = "https://production-sfo.browserless.io/stealth/bql"


# Polish month abbreviations for date parsing
MONTHS_PL = {
    'sty': 1, 'lut': 2, 'mar': 3, 'kwi': 4, 'maj': 5, 'cze': 6,
    'lip': 7, 'sie': 8, 'wrz': 9, 'paz': 10, 'paź': 10, 'lis': 11, 'gru': 12
}

# Maximum delivery days to consider (filter out slow shippers)
MAX_DELIVERY_DAYS = 4


@dataclass
class CompetitorOffer:
    """Represents a competitor's offer"""
    seller_login: str
    seller_id: str
    price: float
    currency: str
    rating_percent: float
    rating_count: int
    is_super_seller: bool
    is_company: bool
    delivery_text: str
    delivery_days: Optional[int]
    offer_id: str
    
    def to_dict(self) -> dict:
        return {
            'seller_login': self.seller_login,
            'seller_id': self.seller_id,
            'price': self.price,
            'currency': self.currency,
            'rating_percent': self.rating_percent,
            'rating_count': self.rating_count,
            'is_super_seller': self.is_super_seller,
            'is_company': self.is_company,
            'delivery_text': self.delivery_text,
            'delivery_days': self.delivery_days,
            'offer_id': self.offer_id
        }


def parse_delivery_days(delivery_text: str, today: Optional[datetime] = None) -> Optional[int]:
    """
    Parse delivery text and return days until delivery.
    Examples:
        "Przewidywana dostawa: we wtorek" -> days until that weekday
        "Przewidywana dostawa: śr. 14 sty." -> specific date
        "dostawa za 13 – 17 dni" -> 15 (average, Chinese seller!)
        "dostawa za 5 dni" -> 5
        "Dostawa od 19,99 zł" -> None (price only, no time info)
    """
    if today is None:
        today = datetime.now()
    
    text = delivery_text.lower()
    
    # Check for "dostawa za X – Y dni" (Chinese sellers!)
    match = re.search(r'dostawa\s+za\s+(\d+)\s*[–-]\s*(\d+)\s*dni', text)
    if match:
        min_days = int(match.group(1))
        max_days = int(match.group(2))
        return (min_days + max_days) // 2  # Average
    
    # Check for "dostawa za X dni"
    match = re.search(r'dostawa\s+za\s+(\d+)\s*dni', text)
    if match:
        return int(match.group(1))
    
    # Check for specific date like "14 sty"
    text_clean = text.replace('ź', 'z').replace('ó', 'o')
    match = re.search(r'(\d{1,2})\s+(sty|lut|mar|kwi|maj|cze|lip|sie|wrz|paz|lis|gru)', text_clean)
    if match:
        day = int(match.group(1))
        month = MONTHS_PL.get(match.group(2), 1)
        year = today.year
        if month < today.month:
            year += 1
        try:
            delivery_date = datetime(year, month, day)
            return (delivery_date - today).days
        except ValueError:
            pass
    
    # Check for day names (Polish)
    day_names = {
        'poniedziałek': 0, 'poniedzialek': 0,
        'wtorek': 1,
        'środa': 2, 'sroda': 2, 'środę': 2, 'srode': 2,
        'czwartek': 3,
        'piątek': 4, 'piatek': 4,
        'sobota': 5, 'sobotę': 5, 'sobote': 5,
        'niedziela': 6, 'niedzielę': 6, 'niedziele': 6
    }
    
    for day_name, day_offset in day_names.items():
        if day_name in text:
            today_weekday = today.weekday()
            days_until = (day_offset - today_weekday) % 7
            if days_until == 0:
                days_until = 7  # Next week if same day
            return days_until
    
    return None


def fetch_page(url: str, timeout: int = 120) -> Optional[str]:
    """Fetch page using Browserless.io with solve for CAPTCHA."""
    print(f"[LOG] Fetching: {url}")
    
    query = '''mutation { 
        goto(url: "''' + url + '''", waitUntil: networkIdle, timeout: 60000) { status } 
        solve { found solved }
        html { html } 
    }'''
    
    api_url = f"{BROWSERLESS_ENDPOINT}?token={BROWSERLESS_TOKEN}&proxy=residential"
    
    try:
        response = requests.post(api_url, json={"query": query}, timeout=timeout)
        
        if response.status_code != 200:
            print(f"[ERROR] Browserless returned {response.status_code}")
            return None
        
        data = response.json()
        
        if 'errors' in data:
            print(f"[ERROR] GraphQL errors: {data['errors']}")
            return None
        
        html = data.get('data', {}).get('html', {}).get('html', '')
        status = data.get('data', {}).get('goto', {}).get('status')
        
        print(f"[LOG] Page status: {status}, HTML: {len(html)} bytes")
        
        if 'captcha-delivery' in html:
            print(f"[ERROR] DataDome CAPTCHA detected")
            return None
        
        return html
        
    except Exception as e:
        print(f"[ERROR] {e}")
        return None


def extract_comparison_url(html: str, offer_url: str) -> Optional[str]:
    """Extract /oferty-produktu/ URL from offer page.
    Tries to find the one matching the product from offer URL."""
    
    # Extract product slug from offer URL to match
    offer_match = re.search(r'/oferta/([^/]+)-\d+', offer_url)
    product_slug = offer_match.group(1) if offer_match else None
    
    # Find all /oferty-produktu/ links
    matches = re.findall(r'/oferty-produktu/([^"\'<>\s]+)', html)
    
    if product_slug:
        # Try to find one that matches our product
        for match in matches:
            if product_slug.split('-')[0] in match.lower():
                return f"https://allegro.pl/oferty-produktu/{match}"
    
    # Fallback to first match
    if matches:
        return f"https://allegro.pl/oferty-produktu/{matches[0]}"
    
    return None


def parse_offers(html: str) -> List[CompetitorOffer]:
    """Parse competitor offers from product comparison page."""
    soup = BeautifulSoup(html, 'html.parser')
    offers = []
    seen = set()
    
    for script in soup.find_all('script', type='application/json'):
        text = script.get_text()
        if '__listing_StoreState' not in text:
            continue
        
        try:
            data = json.loads(text)
            items = data.get('__listing_StoreState', {}).get('items', {}).get('elements', [])
            
            for item in items:
                seller = item.get('seller', {})
                if not seller:
                    continue
                
                seller_login = seller.get('login', '')
                offer_id = item.get('id', '')
                
                if not seller_login or offer_id in seen:
                    continue
                seen.add(offer_id)
                
                # Price
                price_data = item.get('price', {}).get('mainPrice', {})
                try:
                    price = float(price_data.get('amount', '0'))
                except (ValueError, TypeError):
                    price = 0.0
                
                # Delivery - check ALL shipping labels for time info
                shipping = item.get('shipping', {}).get('summary', {}).get('labels', [])
                delivery_text = ''
                for label in shipping:
                    txt = label.get('text', '')
                    # Skip price-only labels like "Dostawa od 19,99 zł"
                    if 'dostawa od' in txt.lower() and 'zł' in txt.lower():
                        continue
                    # Look for actual delivery time
                    if 'dostawa' in txt.lower() or 'dni' in txt.lower():
                        delivery_text = txt
                        break
                
                delivery_days = parse_delivery_days(delivery_text)
                
                offer = CompetitorOffer(
                    seller_login=seller_login,
                    seller_id=seller.get('id', ''),
                    price=price,
                    currency=price_data.get('currency', 'PLN'),
                    rating_percent=seller.get('positiveFeedbackPercent', 0),
                    rating_count=seller.get('positiveFeedbackCount', 0),
                    is_super_seller=seller.get('superSeller', False),
                    is_company=seller.get('company', False),
                    delivery_text=delivery_text,
                    delivery_days=delivery_days,
                    offer_id=offer_id
                )
                offers.append(offer)
            
            break
            
        except json.JSONDecodeError:
            continue
    
    return offers


def filter_slow_delivery(offers: List[CompetitorOffer], max_days: int = MAX_DELIVERY_DAYS) -> List[CompetitorOffer]:
    """Filter out offers with slow delivery."""
    filtered = []
    skipped = []
    
    for offer in offers:
        if offer.delivery_days is not None and offer.delivery_days > max_days:
            skipped.append(offer)
            continue
        filtered.append(offer)
    
    if skipped:
        print(f"[LOG] Filtered {len(skipped)} slow delivery offers (>{max_days} days):")
        for o in skipped:
            print(f"      - {o.seller_login}: {o.price} PLN ({o.delivery_days}d)")
    
    return filtered


def scrape_competitor_prices(offer_url: str, max_delivery_days: int = MAX_DELIVERY_DAYS) -> Dict[str, Any]:
    """
    Main function: scrape competitor prices for Allegro offer.
    
    Steps:
    1. Fetch offer page
    2. Extract /oferty-produktu/ URL
    3. Fetch comparison page
    4. Parse and filter offers
    """
    print(f"\n[1/4] Fetching offer page...")
    html = fetch_page(offer_url)
    if not html:
        return {"error": "Failed to fetch offer page"}
    
    print(f"[2/4] Extracting comparison URL...")
    comparison_url = extract_comparison_url(html, offer_url)
    if not comparison_url:
        return {"error": "Could not find comparison URL"}
    print(f"[LOG] Found: {comparison_url}")
    
    print(f"[3/4] Fetching comparison page...")
    comparison_html = fetch_page(comparison_url)
    if not comparison_html:
        return {"error": "Failed to fetch comparison page"}
    
    print(f"[4/4] Parsing offers...")
    all_offers = parse_offers(comparison_html)
    print(f"[LOG] Found {len(all_offers)} total offers")
    
    offers = filter_slow_delivery(all_offers, max_delivery_days)
    print(f"[LOG] {len(offers)} offers after filtering")
    
    # Analysis
    my_offers = [o for o in offers if o.seller_login.lower() == 'retriever_shop']
    competitors = [o for o in offers if o.seller_login.lower() != 'retriever_shop']
    
    my_price = my_offers[0].price if my_offers else None
    cheapest = min(competitors, key=lambda x: x.price) if competitors else None
    
    return {
        "my_price": my_price,
        "total_offers": len(offers),
        "competitor_count": len(competitors),
        "cheapest_competitor": {
            "seller": cheapest.seller_login,
            "price": cheapest.price,
            "delivery": cheapest.delivery_text
        } if cheapest else None,
        "price_diff": round(my_price - cheapest.price, 2) if my_price and cheapest else None,
        "competitors": [o.to_dict() for o in competitors]
    }


def main():
    parser = argparse.ArgumentParser(description='Scrape Allegro competitor prices')
    parser.add_argument('url', nargs='?', help='Allegro offer URL')
    parser.add_argument('--test', action='store_true', help='Run test')
    parser.add_argument('--max-days', type=int, default=MAX_DELIVERY_DAYS, help='Max delivery days')
    
    args = parser.parse_args()
    
    if args.test:
        test_url = "https://allegro.pl/oferta/szelki-dla-psa-truelove-front-line-premium-xl-granatowe-18180401323"
        print(f"Testing with: {test_url}")
        result = scrape_competitor_prices(test_url, args.max_days)
    elif args.url:
        result = scrape_competitor_prices(args.url, args.max_days)
    else:
        parser.print_help()
        return
    
    print("\n" + "="*60)
    print("RESULTS")
    print("="*60)
    
    if 'error' in result:
        print(f"Error: {result['error']}")
        return
    
    print(f"My price: {result['my_price']} PLN")
    print(f"Competitors: {result['competitor_count']}")
    
    if result['cheapest_competitor']:
        cc = result['cheapest_competitor']
        print(f"Cheapest: {cc['seller']} @ {cc['price']} PLN")
        print(f"Price diff: {result['price_diff']} PLN")
    
    print("\n--- All competitors ---")
    for c in result['competitors']:
        days = f"{c['delivery_days']}d" if c.get('delivery_days') is not None else "?"
        print(f"  {c['seller_login']:25} | {c['price']:>8.2f} PLN | {days}")


if __name__ == '__main__':
    main()
