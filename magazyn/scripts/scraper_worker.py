"""
Allegro Price Scraper Worker

Checks competitor prices for your Allegro offers.
Goes directly to each offer page and finds cheapest competitor.
"""

import argparse
import os
import time
import re
import requests
import random
from decimal import Decimal

try:
    import undetected_chromedriver as uc
    UNDETECTED_AVAILABLE = True
except ImportError:
    UNDETECTED_AVAILABLE = False
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service as ChromeService
    from selenium.webdriver.chrome.options import Options
    from webdriver_manager.chrome import ChromeDriverManager

from selenium.webdriver.common.by import By


MAGAZYN_URL = "https://magazyn.retrievershop.pl"
BATCH_SIZE = 5  # Reduced from 10 to avoid rate limiting
POLL_INTERVAL = 30  # seconds
MIN_DELAY_BETWEEN_OFFERS = 5  # Minimum 5 seconds between offers
MAX_DELAY_BETWEEN_OFFERS = 15  # Maximum 15 seconds (random)

# Rotate user agents to avoid detection
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0"
]


def setup_chrome_driver():
    """Setup Chrome driver with anti-detection measures."""
    # Use persistent profile to keep cookies/login
    profile_path = os.path.abspath("./allegro_scraper_profile")
    os.makedirs(profile_path, exist_ok=True)
    
    # Random user agent
    user_agent = random.choice(USER_AGENTS)
    
    if UNDETECTED_AVAILABLE:
        print("Using undetected-chromedriver for better anti-detection")
        options = uc.ChromeOptions()
        options.add_argument(f"--user-data-dir={profile_path}")
        options.add_argument("--profile-directory=Default")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--start-maximized")
        options.add_argument(f"--user-agent={user_agent}")
        
        driver = uc.Chrome(options=options, version_main=None)
        return driver
    else:
        print("Warning: undetected-chromedriver not installed, using standard selenium")
        print("Install with: pip install undetected-chromedriver")
        chrome_options = Options()
        chrome_options.add_argument(f"--user-data-dir={profile_path}")
        chrome_options.add_argument("--profile-directory=Default")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option("useAutomationExtension", False)
        chrome_options.add_argument("--start-maximized")
        chrome_options.add_argument("--no-first-run")
        chrome_options.add_argument("--no-default-browser-check")
        chrome_options.add_argument(f"--user-agent={user_agent}")
        
        service = ChromeService(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    
    # Hide webdriver property
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    
    return driver


def check_offer_price(driver, offer_url, my_price):
    """
    Go to Allegro offer page and find cheapest competitor price from "Inne oferty" section.
    
    The offer_url already contains #inne-oferty-produktu fragment.
    
    Strategy:
    1. Open offer page (link includes #inne-oferty-produktu)
    2. Wait for "Inne oferty" section to load
    3. Extract all offers with price, seller, and delivery time
    4. Filter: only offers with delivery time <= 4 days
    5. Find cheapest competitor (excluding offers >= our price)
    6. Return: competitor_price, competitor_seller, competitor_url, delivery_days
    
    Returns:
        dict with keys: price, seller, url, delivery_days
        or None if no cheaper competitor found
    """
    try:
        print(f"  Checking: {offer_url}")
        driver.get(offer_url)
        time.sleep(3)  # Wait for page load
        
        # Check for IP block or CAPTCHA
        page_source = driver.page_source.lower()
        
        # Check for IP block
        if "zostałeś zablokowany" in page_source or "you have been blocked" in page_source:
            print("\n" + "="*60)
            print("⛔ IP BLOCKED BY ALLEGRO!")
            print("="*60)
            print("Your IP has been blocked by Allegro's anti-bot protection.")
            print("This happens when scraping too fast or too many requests.")
            print("\nRECOMMENDATIONS:")
            print("1. Wait 30-60 minutes before retrying")
            print("2. Use VPN or change IP address")
            print("3. Reduce scraping speed (already set to 5-15s delay)")
            print("4. Reduce batch size (currently 5 offers)")
            print("="*60 + "\n")
            raise Exception("IP_BLOCKED")
        
        # Check for CAPTCHA
        captcha_detected = False
        try:
            # Look for specific CAPTCHA elements
            captcha_iframes = driver.find_elements(By.CSS_SELECTOR, "iframe[src*='captcha-delivery']")
            if captcha_iframes and len(captcha_iframes) > 0:
                iframe = captcha_iframes[0]
                if iframe.is_displayed() and iframe.size['width'] > 0:
                    captcha_detected = True
            
            if not captcha_detected:
                captcha_forms = driver.find_elements(By.CSS_SELECTOR, "#captcha-form, .captcha-container")
                for elem in captcha_forms:
                    if elem.is_displayed() and elem.size['width'] > 0:
                        captcha_detected = True
                        break
        except Exception as e:
            print(f"  CAPTCHA check error: {e}")
        
        if captcha_detected:
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
                try:
                    captcha_still_there = False
                    if len(driver.find_elements(By.CSS_SELECTOR, "iframe[src*='captcha-delivery']")) > 0:
                        captcha_still_there = True
                    elif len(driver.find_elements(By.CSS_SELECTOR, "#captcha-form, .captcha-container")) > 0:
                        captcha_still_there = True
                    
                    if not captcha_still_there:
                        elapsed = int(time.time() - captcha_start)
                        print(f"✓ CAPTCHA solved after {elapsed}s! Continuing...\n")
                        time.sleep(2)
                        break
                    else:
                        print("    Still waiting for CAPTCHA to be solved...")
                except:
                    break
        
        # Wait for "Inne oferty" section to load
        time.sleep(2)
        
        html = driver.page_source
        
        # Parse offers from "Inne oferty" section
        # Look for offer cards containing price, seller name, and delivery time
        
        offers = []
        
        # Strategy 1: Find offer cards with data-box-name="offer-items"
        try:
            offer_cards = driver.find_elements(By.CSS_SELECTOR, "[data-box-name='offer-items'] > article, [data-box-name='offer-items'] > div > article")
            
            for card in offer_cards:
                try:
                    # Extract price
                    price_elem = card.find_element(By.CSS_SELECTOR, "[data-price], [data-analytics-click-label*='price']")
                    price_text = price_elem.text if price_elem else ""
                    
                    # Extract delivery time (in days)
                    delivery_elem = card.find_elements(By.XPATH, ".//*[contains(text(), 'dni') or contains(text(), 'dzień')]")
                    delivery_days = None
                    if delivery_elem:
                        delivery_text = delivery_elem[0].text
                        # Extract number from "dostawa w 2 dni" or similar
                        match = re.search(r'(\d+)\s*dzi', delivery_text)
                        if match:
                            delivery_days = int(match.group(1))
                    
                    # Extract seller name
                    seller_elem = card.find_elements(By.CSS_SELECTOR, "[data-role='seller-link'], a[href*='/uzytkownik/']")
                    seller_name = seller_elem[0].text if seller_elem else "Unknown"
                    
                    # Extract offer URL
                    offer_link_elem = card.find_elements(By.CSS_SELECTOR, "a[href*='/oferta/']")
                    offer_link = offer_link_elem[0].get_attribute("href") if offer_link_elem else ""
                    
                    # Parse price
                    price_match = re.search(r'([\d\s,]+)', price_text.replace(' ', ''))
                    if price_match:
                        price_str = price_match.group(1).replace(',', '.').replace(' ', '')
                        price = Decimal(price_str)
                        
                        offers.append({
                            'price': price,
                            'seller': seller_name,
                            'url': offer_link,
                            'delivery_days': delivery_days
                        })
                except Exception as e:
                    continue
        except Exception as e:
            print(f"  Error parsing offer cards: {e}")
        
        # Strategy 2: Fallback - parse HTML for JSON data
        if not offers:
            json_pattern = r'"sellerLogin":\s*"([^"]+)"[^}]*"price"[^}]*"amount":\s*"?([\d.]+)"?'
            matches = re.findall(json_pattern, html)
            for seller, price_str in matches:
                try:
                    price = Decimal(price_str.replace(',', '.'))
                    offers.append({
                        'price': price,
                        'seller': seller,
                        'url': offer_url,  # Fallback URL
                        'delivery_days': None
                    })
                except:
                    continue
        
        if not offers:
            return None
        
        # Filter offers by delivery time (max 4 days) and price (cheaper than ours)
        my_price_decimal = Decimal(str(my_price).replace(',', '.'))
        
        filtered_offers = []
        for offer in offers:
            # Skip if delivery time is known and > 4 days
            if offer['delivery_days'] is not None and offer['delivery_days'] > 4:
                continue
            
            # Skip if price >= our price
            if offer['price'] >= my_price_decimal:
                continue
            
            filtered_offers.append(offer)
        
        if not filtered_offers:
            return None
        
        # Sort by price and return cheapest
        filtered_offers.sort(key=lambda x: x['price'])
        cheapest = filtered_offers[0]
        
        return {
            'price': str(cheapest['price']),
            'seller': cheapest['seller'],
            'url': cheapest['url'],
            'delivery_days': cheapest['delivery_days']
        }
        
    except Exception as e:
        print(f"  Error checking offer: {e}")
        return None


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
                
                try:
                    competitor_data = check_offer_price(driver, url, my_price)
                    
                    if competitor_data:
                        print(f"       Competitor: {competitor_data['price']} zł ({competitor_data['seller']}) ✓")
                        if competitor_data['delivery_days']:
                            print(f"       Delivery: {competitor_data['delivery_days']} days")
                        results.append({
                            "offer_id": offer_id,
                            "competitor_price": competitor_data['price'],
                            "competitor_seller": competitor_data['seller'],
                            "competitor_url": competitor_data['url'],
                            "competitor_delivery_days": competitor_data.get('delivery_days')
                        })
                    else:
                        print(f"       No cheaper competitor found")
                except Exception as e:
                    if "IP_BLOCKED" in str(e):
                        print("\n⛔ Stopping scraper due to IP block")
                        # Submit results collected so far
                        if results:
                            submit_results(results)
                        return  # Exit the program
                    else:
                        print(f"       Error: {e}")
                        continue
                
                print()
                
                # Random delay between offers to avoid rate limiting
                delay = random.randint(MIN_DELAY_BETWEEN_OFFERS, MAX_DELAY_BETWEEN_OFFERS)
                print(f"  Waiting {delay}s before next offer...")
                time.sleep(delay)
            
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
