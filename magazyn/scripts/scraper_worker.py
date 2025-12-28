"""
Allegro Price Scraper Worker

Checks competitor prices for your Allegro offers.
Goes directly to each offer page and finds cheapest competitor.

STEALTH MODE: Multiple anti-detection techniques implemented.
"""

import argparse
import os
import time
import re
import requests
import random
import json
import zipfile
import shutil
from decimal import Decimal
from urllib.parse import urlparse

from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager

# Try selenium-stealth for extra protection
try:
    from selenium_stealth import stealth
    SELENIUM_STEALTH_AVAILABLE = True
except ImportError:
    SELENIUM_STEALTH_AVAILABLE = False


MAGAZYN_URL = "https://magazyn.retrievershop.pl"
BATCH_SIZE = 3  # Reduced to 3 to avoid DataDome
POLL_INTERVAL = 30  # seconds
# With rotating proxy (new IP per request) we can be much faster
MIN_DELAY_BETWEEN_OFFERS = 5   # Minimum 5 seconds between offers  
MAX_DELAY_BETWEEN_OFFERS = 15  # Maximum 15 seconds (rotating proxy = new IP each time)
PROXY_URL = None  # Proxy server

# ===== STEALTH CONFIG =====
# Real Chrome user agents from real browsers (updated Dec 2024)
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
]

# Mobile user agents (for mobile mode)
MOBILE_USER_AGENTS = [
    "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1",
]

# Random screen resolutions (common desktop)
SCREEN_RESOLUTIONS = [
    (1920, 1080), (1366, 768), (1536, 864), (1440, 900),
    (1280, 720), (1600, 900), (2560, 1440), (1680, 1050),
]

# Languages for Accept-Language header
LANGUAGES = ["pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7", "pl,en-US;q=0.7,en;q=0.3"]

# Mobile mode flag
MOBILE_MODE = False


def apply_stealth_scripts(driver):
    """Apply minimal stealth JavaScript to hide automation.
    
    Note: Most stealth is already handled by selenium-stealth library.
    This function only applies additional patches not covered by the library.
    """
    stealth_scripts = [
        # Hide webdriver property (critical)
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});",
        
        # Hide automation-related properties
        """
        delete window.cdc_adoQpoasnfa76pfcZLmcfl_Array;
        delete window.cdc_adoQpoasnfa76pfcZLmcfl_Promise;
        delete window.cdc_adoQpoasnfa76pfcZLmcfl_Symbol;
        """,
    ]
    
    for script in stealth_scripts:
        try:
            driver.execute_script(script)
        except Exception:
            pass  # Some scripts may fail, continue with others
    
    return driver


def create_proxy_extension(proxy_url):
    """Create a Chrome extension for proxy authentication and return ZIP path.
    
    Args:
        proxy_url: Proxy URL in format http://user:pass@host:port
        
    Returns:
        Path to the zipped extension (.crx)
    """
    # Parse proxy URL
    parsed = urlparse(proxy_url)
    proxy_user = parsed.username or ""
    proxy_pass = parsed.password or ""
    proxy_host = parsed.hostname
    proxy_port = parsed.port or 8080
    
    # Extension directory
    ext_dir = os.path.abspath("./proxy_auth_extension")
    
    # Read template files
    manifest_path = os.path.join(ext_dir, "manifest.json")
    background_path = os.path.join(ext_dir, "background.js")
    
    with open(background_path, 'r') as f:
        background_js = f.read()
    
    # Replace placeholders
    background_js = background_js.replace("PROXY_HOST", proxy_host)
    background_js = background_js.replace("PROXY_PORT", str(proxy_port))
    background_js = background_js.replace("PROXY_USER", proxy_user)
    background_js = background_js.replace("PROXY_PASS", proxy_pass)
    
    # Write configured extension to temp dir
    configured_ext_dir = os.path.abspath("./proxy_auth_configured")
    os.makedirs(configured_ext_dir, exist_ok=True)
    
    # Copy manifest
    shutil.copy(manifest_path, os.path.join(configured_ext_dir, "manifest.json"))
    
    # Write configured background.js
    with open(os.path.join(configured_ext_dir, "background.js"), 'w') as f:
        f.write(background_js)
    
    # Create ZIP file (Chrome extension format)
    zip_path = os.path.abspath("./proxy_auth.zip")
    with zipfile.ZipFile(zip_path, 'w') as zipf:
        zipf.write(os.path.join(configured_ext_dir, "manifest.json"), "manifest.json")
        zipf.write(os.path.join(configured_ext_dir, "background.js"), "background.js")
    
    print(f"[PROXY] Extension created: {proxy_host}:{proxy_port} (user: {proxy_user})")
    print(f"[PROXY] Extension ZIP: {zip_path}")
    return zip_path


def human_like_mouse_movement(driver):
    """Simulate human-like mouse movement using JavaScript."""
    try:
        # Random mouse movements
        movements = random.randint(3, 7)
        for _ in range(movements):
            x = random.randint(100, 800)
            y = random.randint(100, 600)
            driver.execute_script(f"""
                var evt = new MouseEvent('mousemove', {{
                    bubbles: true, cancelable: true, clientX: {x}, clientY: {y}
                }});
                document.dispatchEvent(evt);
            """)
            time.sleep(random.uniform(0.1, 0.3))
    except:
        pass


def setup_chrome_driver():
    """Setup Chrome driver with MAXIMUM anti-detection measures."""
    # Random user agent
    if MOBILE_MODE:
        user_agent = random.choice(MOBILE_USER_AGENTS)
        window_size = (412, 915)  # Mobile size
    else:
        user_agent = random.choice(USER_AGENTS)
        window_size = random.choice(SCREEN_RESOLUTIONS)
    
    language = random.choice(LANGUAGES)
    
    print(f"[STEALTH] User-Agent: {user_agent[:50]}...")
    print(f"[STEALTH] Window: {window_size[0]}x{window_size[1]}")
    print(f"[STEALTH] Mobile mode: {MOBILE_MODE}")
    
    if PROXY_URL:
        # Use regular Selenium + Chrome extension (extension sets proxy)
        print("Using regular Selenium + proxy extension")
        
        options_selenium = webdriver.ChromeOptions()
        
        # NO persistent profile - it causes Chrome process leaks
        # Each run creates new session = clean start + proper cleanup
        
        # Set page load strategy
        options_selenium.page_load_strategy = 'normal'
        
        # Basic args
        options_selenium.add_argument("--no-sandbox")
        options_selenium.add_argument("--disable-dev-shm-usage")
        options_selenium.add_argument(f"--user-agent={user_agent}")
        options_selenium.add_argument(f"--window-size={window_size[0]},{window_size[1]}")
        options_selenium.add_argument(f"--lang={language.split(',')[0]}")
        
        # Anti-detection
        options_selenium.add_argument("--disable-blink-features=AutomationControlled")
        options_selenium.add_argument("--disable-infobars")
        options_selenium.add_argument("--disable-popup-blocking")
        
        # Bandwidth optimization - disable images to save proxy transfer
        # Images on Allegro can be 1-3 MB per page, we only need JSON data
        prefs = {
            "profile.managed_default_content_settings.images": 2,  # Block images
            "profile.default_content_setting_values.notifications": 2,  # Block notifications
        }
        options_selenium.add_experimental_option("prefs", prefs)
        print("[PROXY] Bandwidth saver: images DISABLED (saves ~2-3 MB per page)")
        
        # Load proxy extension (extension will set proxy + handle auth)
        proxy_ext_zip_path = create_proxy_extension(PROXY_URL)
        options_selenium.add_extension(proxy_ext_zip_path)
        
        # Parse proxy for logging
        parsed = urlparse(PROXY_URL)
        print(f"[PROXY] Extension loaded: {parsed.hostname}:{parsed.port} (user: {parsed.username})")
        
        service = ChromeService(ChromeDriverManager().install())
        driver = webdriver.Chrome(
            service=service,
            options=options_selenium
        )
        
        # Apply stealth scripts via CDP
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": """
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                Object.defineProperty(navigator, 'languages', {get: () => ['pl-PL', 'pl', 'en-US', 'en']});
                window.chrome = {runtime: {}};
            """
        })
        
        # Apply selenium-stealth if available
        if SELENIUM_STEALTH_AVAILABLE:
            print("[STEALTH] Applying selenium-stealth patches...")
            stealth(driver,
                languages=["pl-PL", "pl", "en-US", "en"],
                vendor="Google Inc.",
                platform="Win32",
                webgl_vendor="Intel Inc.",
                renderer="Intel Iris OpenGL Engine",
                fix_hairline=True,
            )
        
        return driver
    else:
        # No proxy - use standard selenium
        print("Using standard Selenium (no proxy)")
        
        chrome_options = Options()
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option("useAutomationExtension", False)
        chrome_options.add_argument("--no-first-run")
        chrome_options.add_argument("--no-default-browser-check")
        chrome_options.add_argument(f"--user-agent={user_agent}")
        chrome_options.add_argument(f"--window-size={window_size[0]},{window_size[1]}")
        chrome_options.add_argument(f"--lang={language.split(',')[0]}")
        
        # Bandwidth optimization - disable images (even without proxy, faster loading)
        prefs = {
            "profile.managed_default_content_settings.images": 2,
            "profile.default_content_setting_values.notifications": 2,
        }
        chrome_options.add_experimental_option("prefs", prefs)
        
        service = ChromeService(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        
        # Hide webdriver property
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        
        return driver


def check_offer_price(driver, offer_url, my_price):
    """
    Go to Allegro offer page and find cheapest competitor price from "Inne oferty" section.
    
    Strategy:
    1. Open offer page (link includes #inne-oferty-produktu)
    2. Wait for "Inne oferty" section to load
    3. Extract all offers with price and seller
    4. Find cheapest competitor (excluding offers >= our price)
    5. Return: competitor_price, competitor_seller, competitor_url
    """
    try:
        print(f"  Checking: {offer_url}")
        driver.get(offer_url)
        
        # Wait for SPA to load (Allegro is React-based)
        time.sleep(random.uniform(5, 8))
        
        # Apply stealth scripts on every page load
        apply_stealth_scripts(driver)
        
        # Human-like behavior
        time.sleep(random.uniform(2, 4))
        scroll_amount = random.randint(300, 700)
        driver.execute_script(f"window.scrollTo(0, {scroll_amount});")
        time.sleep(random.uniform(0.5, 1.5))
        human_like_mouse_movement(driver)
        driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(random.uniform(0.3, 0.8))
        
        # Check for IP block or CAPTCHA
        page_source = driver.page_source.lower()
        
        # Save page for debugging (only on errors)
        def save_debug_page():
            try:
                with open("last_page_debug.html", "w", encoding="utf-8") as f:
                    f.write(driver.page_source)
            except:
                pass
        
        # Check for IP block - hard blocks only (NOT captcha)
        block_keywords = [
            "zostałeś zablokowany",
            "you have been blocked", 
            "zablokowano",
            "access denied",
            "dostęp zablokowany"
        ]
        
        for keyword in block_keywords:
            if keyword in page_source:
                print(f"\n{'='*60}")
                print("[!] IP BLOCKED BY ALLEGRO!")
                print(f"{'='*60}")
                print(f"Block keyword detected: '{keyword}'")
                print("\nRECOMMENDATIONS:")
                print("1. Wait 30-60 minutes before retrying")
                print("2. Use VPN or change IP address")
                print("3. Consider using different proxy or residential IP")
                print(f"{'='*60}\n")
                save_debug_page()
                return None
        
        # Check for CAPTCHA (including DataDome)
        captcha_detected = False
        try:
            if 'captcha-delivery' in page_source or 'datadome' in page_source:
                captcha_detected = True
            
            if not captcha_detected:
                captcha_iframes = driver.find_elements(By.CSS_SELECTOR, "iframe[src*='captcha-delivery'], iframe[title*='captcha'], iframe[title*='DataDome']")
                if captcha_iframes and len(captcha_iframes) > 0:
                    iframe = captcha_iframes[0]
                    if iframe.is_displayed() and iframe.size['width'] > 0:
                        captcha_detected = True
        except Exception as e:
            print(f"  CAPTCHA check error: {e}")
        
        if captcha_detected:
            print(f"\n{'='*60}")
            print("[!] CAPTCHA DETECTED!")
            print(f"{'='*60}")
            print("Please solve the CAPTCHA manually in the Chrome window.")
            print("The script will wait and continue automatically once solved.")
            print(f"{'='*60}\n")
            
            # Wait until CAPTCHA is solved
            captcha_start = time.time()
            while True:
                time.sleep(5)
                try:
                    current_title = driver.title.lower()
                    page_source_check = driver.page_source.lower()
                    
                    # CAPTCHA indicators
                    has_captcha_iframe = len(driver.find_elements(By.CSS_SELECTOR, "iframe[src*='captcha-delivery']")) > 0
                    has_captcha_text = "captcha-delivery" in page_source_check
                    is_generic_title = current_title.strip() == "allegro.pl"
                    
                    # If page has real content (not CAPTCHA), continue
                    if not has_captcha_iframe and not has_captcha_text and not is_generic_title:
                        elapsed = int(time.time() - captcha_start)
                        print(f"[OK] CAPTCHA solved after {elapsed}s!")
                        time.sleep(2)
                        break
                        
                    # Timeout after 5 minutes
                    if time.time() - captcha_start > 300:
                        print("[!] CAPTCHA timeout (5min) - skipping offer")
                        return None
                except Exception as e:
                    print(f"[!] Error checking CAPTCHA status: {e}")
                    break
        
        # Check for block page AFTER CAPTCHA solved
        page_source_after = driver.page_source.lower()
        for keyword in block_keywords + ["coś w zachowaniu twojej przeglądarki"]:
            if keyword in page_source_after:
                print(f"\n[!] IP BLOCKED AFTER CAPTCHA (keyword: '{keyword}')")
                print("Allegro blocked your IP even after solving CAPTCHA.")
                print("This IP is flagged - switching required.\n")
                save_debug_page()
                raise Exception("IP_BLOCKED_AFTER_CAPTCHA")
        
        # Parse JSON data embedded in page
        html = driver.page_source
        
        # Allegro stores data in JSON - extract "mainPrice", "seller" and "delivery" fields
        # Pattern: "mainPrice":{"amount":"230.99","currency":"PLN"}
        price_pattern = r'"mainPrice":\{"amount":"([^"]+)","currency":"PLN"\}'
        price_matches = re.findall(price_pattern, html)
        
        # Pattern: "seller":{"id":"...","title":"...","login":"tiptop24pl"
        seller_pattern = r'"seller":\{[^}]*"login":"([^"]+)"'
        seller_matches = re.findall(seller_pattern, html)
        
        # Pattern: "dostawa za X dni" - explicit days format
        delivery_days_pattern = r'dostawa\s+za\s+(\d+)\s+dn'
        delivery_days_matches = re.findall(delivery_days_pattern, html, re.IGNORECASE)
        
        # Pattern: "dostawa za 8 dni" or "dostawa za 8 do 14 dni" (range)
        delivery_range_pattern = r'dostawa\s+(?:za\s+)?(?:\d+\s+do\s+)?(\d+)\s+dn'
        delivery_range_matches = re.findall(delivery_range_pattern, html, re.IGNORECASE)
        
        # Combine both patterns (use range if more matches)
        delivery_text_matches = delivery_range_matches if len(delivery_range_matches) > len(delivery_days_matches) else delivery_days_matches
        
        print(f"  Found {len(price_matches)} prices, {len(seller_matches)} sellers, {len(delivery_text_matches)} delivery times")
        
        # Match prices with sellers and delivery times
        offers = []
        for i, price_str in enumerate(price_matches):
            try:
                price = Decimal(price_str.replace(',', '.'))
                seller = seller_matches[i] if i < len(seller_matches) else 'Unknown'
                
                # Get delivery time (max days)
                delivery_days = None
                if i < len(delivery_text_matches):
                    try:
                        delivery_days = int(delivery_text_matches[i])
                    except (ValueError, IndexError):
                        pass
                
                # FILTER: Skip ONLY if explicitly > 7 days
                # If delivery_days = None (no info), we ACCEPT (don't exclude local sellers)
                if delivery_days is not None and delivery_days > 7:
                    print(f"  Skipping {seller} - delivery {delivery_days} days (China?)")
                    continue
                
                offers.append({
                    'price': price, 
                    'seller': seller, 
                    'url': offer_url,
                    'delivery_days': delivery_days
                })
            except (ValueError, IndexError):
                continue
        
        # Deduplicate by seller (keep lowest price per seller)
        unique_offers = {}
        for offer in offers:
            seller = offer['seller']
            if seller not in unique_offers or offer['price'] < unique_offers[seller]['price']:
                unique_offers[seller] = offer
        
        offers = list(unique_offers.values())
        
        if not offers:
            return {'status': 'no_offers', 'message': 'Nie znaleziono ofert konkurencji'}
        
        # Filter: only cheaper than our price
        my_price_decimal = Decimal(str(my_price).replace(',', '.'))
        filtered_offers = [o for o in offers if o['price'] < my_price_decimal]
        
        print(f"  After filter: {len(filtered_offers)} cheaper offers")
        
        if not filtered_offers:
            return {'status': 'cheapest', 'message': 'Retriever_Shop ma najtańszą cenę'}
        
        # Sort by price and return cheapest
        filtered_offers.sort(key=lambda x: x['price'])
        cheapest = filtered_offers[0]
        
        return {
            'status': 'competitor_cheaper',
            'price': str(cheapest['price']),
            'seller': cheapest['seller'],
            'url': cheapest['url'],
            'delivery_days': cheapest.get('delivery_days')
        }
        
    except Exception as e:
        print(f"  Error checking offer: {e}")
        return None


def get_offers_total():
    """Get total count of offers waiting for check."""
    try:
        url = f"{MAGAZYN_URL}/api/scraper/get_tasks"
        response = requests.get(url, params={"limit": 1}, timeout=10)
        response.raise_for_status()
        data = response.json()
        return data.get("total", 0)
    except Exception as e:
        print(f"[!] Error fetching total: {e}")
        return 0


def get_offers():
    """Fetch offers that need price checking from magazyn API."""
    try:
        url = f"{MAGAZYN_URL}/api/scraper/get_tasks"
        response = requests.get(url, params={"limit": BATCH_SIZE}, timeout=10)
        response.raise_for_status()
        data = response.json()
        offers = data.get("offers", [])
        return offers
    except Exception as e:
        print(f"[!] Error fetching offers: {e}")
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
        print(f"[OK] Submitted {processed} results")
        return True
    except Exception as e:
        print(f"[!] Error submitting results: {e}")
        return False


def warm_up_session(driver):
    """Visit Allegro homepage first to establish cookies and look human."""
    print("[WARMUP] Visiting Allegro homepage first to establish session...")
    
    try:
        # Visit homepage
        print("[WARMUP] Loading allegro.pl...")
        driver.get("https://allegro.pl")
        print("[WARMUP] Page loaded, waiting...")
        time.sleep(random.uniform(3, 5))
        
        # Check what we got
        print(f"[WARMUP] Page title: {driver.title}")
        print(f"[WARMUP] Current URL: {driver.current_url}")
        
        # Apply stealth scripts
        apply_stealth_scripts(driver)
        
        # Simulate browsing behavior
        human_like_mouse_movement(driver)
        
        # Random scroll
        scroll_amount = random.randint(200, 500)
        driver.execute_script(f"window.scrollTo(0, {scroll_amount});")
        time.sleep(random.uniform(1, 2))
        
        # Scroll back
        driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(random.uniform(0.5, 1))
        
        # Check if we landed on homepage or block page
        page_source = driver.page_source.lower()
        if "zostałeś zablokowany" in page_source:
            print("[!] IP BLOCKED even on homepage!")
            return False
        
        print("[OK] Homepage visited successfully, cookies established")
        
        # Wait a bit before starting actual work
        wait_time = random.randint(5, 15)
        print(f"[WARMUP] Waiting {wait_time}s to look more natural...")
        time.sleep(wait_time)
        
        return True
        
    except Exception as e:
        print(f"[!] Warmup failed: {e}")
        return False


def main():
    global MAGAZYN_URL, PROXY_URL, MOBILE_MODE, BATCH_SIZE
    
    # CRITICAL: Kill orphaned Chrome/ChromeDriver before starting
    print("[CLEANUP] Killing orphaned Chrome processes...")
    try:
        os.system("taskkill /F /IM chrome.exe /T >nul 2>&1")
        os.system("taskkill /F /IM chromedriver.exe /T >nul 2>&1")
        time.sleep(1)
    except Exception as e:
        print(f"[CLEANUP] Warning: {e}")
    
    parser = argparse.ArgumentParser(description="Allegro Competitor Price Checker")
    parser.add_argument("--url", required=True, help="Magazyn URL (e.g., https://magazyn.retrievershop.pl)")
    parser.add_argument("--interval", type=int, default=POLL_INTERVAL, help="Poll interval in seconds")
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE, help="Number of offers to check per batch")
    parser.add_argument("--proxy", type=str, default=None, help="Proxy server (e.g., http://user:pass@host:port)")
    parser.add_argument("--mobile", action="store_true", help="Use mobile user-agent and viewport")
    parser.add_argument("--no-warmup", action="store_true", help="Skip warmup (visit homepage first)")
    args = parser.parse_args()
    
    MAGAZYN_URL = args.url.rstrip("/")
    poll_interval = args.interval
    BATCH_SIZE = args.batch_size
    PROXY_URL = args.proxy
    MOBILE_MODE = args.mobile
    
    print("="*70)
    print("Allegro Competitor Price Checker - STEALTH MODE")
    print("="*70)
    print(f"Magazyn URL: {MAGAZYN_URL}")
    print(f"Poll interval: {poll_interval}s")
    print(f"Batch size: {BATCH_SIZE}")
    print(f"Mobile mode: {MOBILE_MODE}")
    if PROXY_URL:
        print(f"Proxy: {PROXY_URL}")
    print("="*70)
    print()
    
    driver = None
    
    try:
        driver = setup_chrome_driver()
        print("[OK] Chrome driver initialized")
        print()
        
        # Warmup - visit homepage first
        if not args.no_warmup:
            warmup_result = warm_up_session(driver)
            if not warmup_result:
                print("[!] Warmup failed - IP may be blocked")
                print("[!] Try using --proxy or wait and try again later")
                return
        
        # Main scraping loop
        while True:
            # Get total count first
            total_offers = get_offers_total()
            offers = get_offers()
            
            if not offers:
                print(f"No offers to check. Waiting {poll_interval}s...")
                time.sleep(poll_interval)
                continue
            
            print(f"\nChecking {len(offers)} offers (total pending: {total_offers})...")
            results = []
            
            for i, offer in enumerate(offers, 1):
                offer_id = offer["offer_id"]
                title = offer.get("title", "Unknown")
                my_price = offer.get("my_price", "0")
                url = offer["url"]
                
                # Calculate global position (batch start + current index)
                global_index = (total_offers - len(offers)) + i
                
                # Truncate title for display
                display_title = title[:40] + "..." if len(title) > 40 else title
                
                print(f"\n[{global_index}/{total_offers}] {display_title}")
                print(f"  My price: {my_price} zł")
                
                try:
                    competitor_data = check_offer_price(driver, url, my_price)
                    
                    if competitor_data:
                        status = competitor_data.get('status')
                        
                        if status == 'competitor_cheaper':
                            print(f"  Competitor: {competitor_data['price']} zł ({competitor_data['seller']})")
                            results.append({
                                "offer_id": offer_id,
                                "status": "competitor_cheaper",
                                "competitor_price": competitor_data['price'],
                                "competitor_seller": competitor_data['seller'],
                                "competitor_url": competitor_data['url'],
                                "competitor_delivery_days": competitor_data.get('delivery_days')
                            })
                        elif status == 'cheapest':
                            print(f"  [OK] Retriever_Shop najtanszy!")
                            results.append({"offer_id": offer_id, "status": "cheapest"})
                        elif status == 'no_offers':
                            print(f"  [!] Brak ofert konkurencji")
                            results.append({"offer_id": offer_id, "status": "no_offers"})
                    else:
                        print(f"  [!] No data returned")
                        
                except Exception as e:
                    if "IP_BLOCKED" in str(e):
                        print("\n[!] Stopping scraper due to IP block")
                        if results:
                            submit_results(results)
                        return
                    else:
                        print(f"  [!] Error: {e}")
                        continue
                
                # Random delay between offers
                delay = random.randint(MIN_DELAY_BETWEEN_OFFERS, MAX_DELAY_BETWEEN_OFFERS)
                print(f"  Waiting {delay}s...")
                time.sleep(delay)
            
            # Submit all results
            if results:
                submit_results(results)
            
    except KeyboardInterrupt:
        print("\nShutting down...")
    except Exception as e:
        print(f"Fatal error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if driver:
            print("Closing browser...")
            try:
                driver.quit()
            except Exception as e:
                print(f"[!] Error closing driver: {e}")
        # Final cleanup - kill any remaining Chrome/ChromeDriver
        print("[CLEANUP] Final Chrome cleanup...")
        try:
            os.system("taskkill /F /IM chrome.exe /T >nul 2>&1")
            os.system("taskkill /F /IM chromedriver.exe /T >nul 2>&1")
        except:
            pass


if __name__ == "__main__":
    main()
