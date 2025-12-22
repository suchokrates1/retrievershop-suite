"""
Allegro Price Scraper Worker

Checks competitor prices for your Allegro offers.
Goes directly to each offer page and finds cheapest competitor.
"""

import argparse
import time
import re
import requests
from decimal import Decimal

from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager


MAGAZYN_URL = "https://magazyn.retrievershop.pl"
BATCH_SIZE = 10
POLL_INTERVAL = 30  # seconds


def setup_chrome_driver():
    """Setup Chrome driver with anti-detection measures."""
    chrome_options = Options()
    
    # Use persistent profile to keep cookies/login
    profile_path = "./allegro_scraper_profile"
    chrome_options.add_argument(f"--user-data-dir={profile_path}")
    
    # Anti-detection
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)
    chrome_options.add_argument("--start-maximized")
    chrome_options.add_argument("--no-first-run")
    chrome_options.add_argument("--no-default-browser-check")
    
    service = ChromeService(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    
    # Hide webdriver property
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    
    return driver


def check_offer_price(driver, offer_url):
    """
    Go to Allegro offer page and find cheapest competitor price.
    
    Strategy:
    1. Open offer page with sorting by price (?order=p)
    2. Look for "Inne oferty" (similar offers) section
    3. Extract competitor prices
    4. Return cheapest (excluding our own price which should be first)
    
    Returns:
        (competitor_price, competitor_url) or (None, error_message)
    """
    try:
        # Add sorting by price parameter
        if '?' in offer_url:
            sorted_url = f"{offer_url}&order=p"
        else:
            sorted_url = f"{offer_url}?order=p"
        
        print(f"    Opening: {sorted_url[:60]}...")
        driver.get(sorted_url)
        time.sleep(3)
        
        # Check for CAPTCHA
        page_content = driver.page_source.lower()
        if "captcha" in page_content or "datadome" in page_content:
            print("\n" + "="*60)
            print("⚠️  CAPTCHA DETECTED!")
            print("="*60)
            print("Please solve the CAPTCHA manually in the Chrome window.")
            print("The script will wait and continue automatically once solved.")
            print("="*60 + "\n")
            
            # Wait until CAPTCHA is solved
            captcha_start = time.time()
            while True:
                time.sleep(5)
                page_content = driver.page_source.lower()
                if "captcha" not in page_content and "datadome" not in page_content:
                    elapsed = int(time.time() - captcha_start)
                    print(f"✓ CAPTCHA solved after {elapsed}s! Continuing...\n")
                    time.sleep(2)
                    break
                else:
                    print("    Still waiting for CAPTCHA to be solved...")
        
        html = driver.page_source
        
        # Multiple strategies to find competitor prices
        
        # Strategy 1: Look for JSON price data
        json_pattern = r'"price":\s*{\s*"amount":\s*"?([\d.]+)"?'
        json_matches = re.findall(json_pattern, html)
        
        # Strategy 2: Look for meta price tags
        meta_pattern = r'<meta[^>]+itemprop="price"[^>]+content="([\d.]+)"'
        meta_matches = re.findall(meta_pattern, html)
        
        # Strategy 3: Look for data-price attributes
        data_pattern = r'data-price="([\d.]+)"'
        data_matches = re.findall(data_pattern, html)
        
        # Strategy 4: Look for offers in "Inne oferty" section
        # This section usually contains similar offers from other sellers
        inne_pattern = r'ofert[ay][^}]*?"price"[^}]*?"amount":\s*"?([\d.]+)"?'
        inne_matches = re.findall(inne_pattern, html, re.IGNORECASE)
        
        # Combine all found prices
        all_price_strings = json_matches + meta_matches + data_matches + inne_matches
        
        if not all_price_strings:
            return None, "No competitor prices found"
        
        # Convert to Decimal and deduplicate
        prices = []
        seen = set()
        for price_str in all_price_strings:
            try:
                price_str = price_str.replace(',', '.')
                price = Decimal(price_str)
                price_key = str(price)
                if price_key not in seen and price > 0:
                    seen.add(price_key)
                    prices.append(price)
            except:
                continue
        
        if not prices:
            return None, "Could not parse any valid prices"
        
        # Sort prices
        prices.sort()
        
        # If only one price found, it's probably our own
        if len(prices) < 2:
            return None, "No competitors found (only our offer)"
        
        # First price is likely ours, second is cheapest competitor
        competitor_price = prices[1]
        
        return str(competitor_price), sorted_url
        
    except Exception as e:
        return None, f"Error: {str(e)}"


def get_offers():
    """Fetch offers that need price checking from magazyn API."""
    try:
        response = requests.get(
            f"{MAGAZYN_URL}/api/scraper/get_tasks",
            params={"limit": BATCH_SIZE},
            timeout=10
        )
        response.raise_for_status()
        data = response.json()
        return data.get("offers", [])
    except Exception as e:
        print(f"Error fetching offers: {e}")
        return []


def submit_results(results):
    """Submit price check results to magazyn API."""
    try:
        response = requests.post(
            f"{MAGAZYN_URL}/api/scraper/submit_results",
            json={"results": results},
            timeout=30
        )
        response.raise_for_status()
        data = response.json()
        processed = data.get('processed', 0)
        print(f"✓ Submitted {processed} results")
        return True
    except Exception as e:
        print(f"Error submitting results: {e}")
        return False


def main():
    global MAGAZYN_URL
    
    parser = argparse.ArgumentParser(description="Allegro Competitor Price Checker")
    parser.add_argument("--url", required=True, help="Magazyn URL (e.g., https://magazyn.retrievershop.pl)")
    parser.add_argument("--interval", type=int, default=POLL_INTERVAL, help="Poll interval in seconds")
    args = parser.parse_args()
    
    MAGAZYN_URL = args.url.rstrip("/")
    poll_interval = args.interval
    
    print("="*70)
    print("Allegro Competitor Price Checker")
    print("="*70)
    print(f"Magazyn URL: {MAGAZYN_URL}")
    print(f"Poll interval: {poll_interval}s")
    print(f"Batch size: {BATCH_SIZE}")
    print("="*70)
    print()
    
    driver = None
    
    try:
        driver = setup_chrome_driver()
        print("✓ Chrome driver initialized")
        print()
        
        while True:
            offers = get_offers()
            
            if not offers:
                print(f"No offers to check. Waiting {poll_interval}s...")
                time.sleep(poll_interval)
                continue
            
            print(f"Checking {len(offers)} offers...")
            print()
            
            results = []
            
            for i, offer in enumerate(offers, 1):
                offer_id = offer["offer_id"]
                title = offer.get("title", "Unknown")
                my_price = offer.get("my_price", "0")
                url = offer["url"]
                
                # Truncate title for display
                display_title = title[:40] + "..." if len(title) > 40 else title
                
                print(f"  [{i}/{len(offers)}] {display_title}")
                print(f"       My price: {my_price} zł")
                
                competitor_price, competitor_url = check_offer_price(driver, url)
                
                if competitor_price:
                    print(f"       Competitor: {competitor_price} zł ✓")
                    results.append({
                        "offer_id": offer_id,
                        "competitor_price": competitor_price,
                        "competitor_url": competitor_url
                    })
                else:
                    print(f"       Error: {competitor_url}")
                    results.append({
                        "offer_id": offer_id,
                        "error": competitor_url
                    })
                
                print()
                
                # Small delay between offers
                time.sleep(2)
            
            # Submit all results
            if results:
                submit_results(results)
            
            print()
            
    except KeyboardInterrupt:
        print("\nShutting down...")
    except Exception as e:
        print(f"Fatal error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if driver:
            print("Closing browser...")
            driver.quit()


if __name__ == "__main__":
    main()
