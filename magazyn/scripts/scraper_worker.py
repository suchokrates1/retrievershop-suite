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

try:
    import undetected_chromedriver as uc
    UNDETECTED_AVAILABLE = True
except ImportError:
    UNDETECTED_AVAILABLE = False
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service as ChromeService
    from selenium.webdriver.chrome.options import Options
    from webdriver_manager.chrome import ChromeDriverManager

# Try selenium-stealth for extra protection
try:
    from selenium_stealth import stealth
    SELENIUM_STEALTH_AVAILABLE = True
except ImportError:
    SELENIUM_STEALTH_AVAILABLE = False

from selenium.webdriver.common.by import By


MAGAZYN_URL = "https://magazyn.retrievershop.pl"
BATCH_SIZE = 3  # Reduced to 3 to avoid DataDome
POLL_INTERVAL = 30  # seconds
MIN_DELAY_BETWEEN_OFFERS = 30  # Minimum 30 seconds between offers
MAX_DELAY_BETWEEN_OFFERS = 90  # Maximum 90 seconds (increased randomness)
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
    """Apply comprehensive stealth JavaScript to hide automation."""
    stealth_scripts = [
        # 1. Hide webdriver property
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});",
        
        # 2. Override plugins to look real
        """
        Object.defineProperty(navigator, 'plugins', {
            get: () => [
                {name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer'},
                {name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai'},
                {name: 'Native Client', filename: 'internal-nacl-plugin'}
            ]
        });
        """,
        
        # 3. Override languages
        "Object.defineProperty(navigator, 'languages', {get: () => ['pl-PL', 'pl', 'en-US', 'en']});",
        
        # 4. Hide automation flags
        "window.chrome = {runtime: {}};",
        
        # 5. Override permissions query
        """
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) => (
            parameters.name === 'notifications' ?
                Promise.resolve({state: Notification.permission}) :
                originalQuery(parameters)
        );
        """,
        
        # 6. Realistic screen dimensions (override if headless)
        """
        Object.defineProperty(screen, 'availWidth', {get: () => screen.width});
        Object.defineProperty(screen, 'availHeight', {get: () => screen.height});
        """,
        
        # 7. Hide automation-related properties
        """
        delete window.cdc_adoQpoasnfa76pfcZLmcfl_Array;
        delete window.cdc_adoQpoasnfa76pfcZLmcfl_Promise;
        delete window.cdc_adoQpoasnfa76pfcZLmcfl_Symbol;
        """,
        
        # 8. Mock battery API
        """
        navigator.getBattery = () => Promise.resolve({
            charging: true,
            chargingTime: 0,
            dischargingTime: Infinity,
            level: 1.0
        });
        """,
        
        # 9. Override connection info
        """
        Object.defineProperty(navigator, 'connection', {
            get: () => ({
                effectiveType: '4g',
                rtt: 50,
                downlink: 10,
                saveData: false
            })
        });
        """,
        
        # 10. Hardware concurrency (realistic CPU cores)
        "Object.defineProperty(navigator, 'hardwareConcurrency', {get: () => 8});",
        
        # 11. Device memory
        "Object.defineProperty(navigator, 'deviceMemory', {get: () => 8});",
        
        # 12. Override toString to hide modifications
        """
        const oldToString = Function.prototype.toString;
        Function.prototype.toString = function() {
            if (this === navigator.permissions.query) {
                return 'function query() { [native code] }';
            }
            return oldToString.call(this);
        };
        """
    ]
    
    for script in stealth_scripts:
        try:
            driver.execute_script(script)
        except Exception as e:
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
    
    if UNDETECTED_AVAILABLE and not PROXY_URL:
        # Use undetected-chromedriver ONLY when no proxy (it blocks extensions)
        print("Using undetected-chromedriver for better anti-detection")
        
        # Use PERSISTENT profile to avoid looking like a bot
        profile_path = os.path.abspath("./allegro_scraper_profile")
        os.makedirs(profile_path, exist_ok=True)
        
        options = uc.ChromeOptions()
        
        # PROFILE - persistent cookies/fingerprint
        options.add_argument(f"--user-data-dir={profile_path}")
        options.add_argument("--profile-directory=ScraperSession")
        
        # Basic Chrome args
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument(f"--user-agent={user_agent}")
        options.add_argument(f"--window-size={window_size[0]},{window_size[1]}")
        options.add_argument(f"--lang={language.split(',')[0]}")
        
        # Anti-detection args
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--disable-infobars")
        options.add_argument("--disable-popup-blocking")
        
        # Make it look more human
        options.add_argument("--enable-features=NetworkService,NetworkServiceInProcess")
        
        # PROXY - undetected-chromedriver BLOCKS extensions, handled below
        proxy_ext_zip_path = None
        if PROXY_URL:
            proxy_ext_zip_path = create_proxy_extension(PROXY_URL)
            
        driver = uc.Chrome(options=options, version_main=None)
        
    elif PROXY_URL:
        # MUST use regular Selenium when proxy auth is needed (extensions)
        print("Using regular Selenium + proxy extension (undetected blocks extensions)")
        from selenium import webdriver
        from selenium.webdriver.chrome.service import Service as ChromeService
        from webdriver_manager.chrome import ChromeDriverManager
        
        # Use PERSISTENT profile
        profile_path = os.path.abspath("./allegro_scraper_profile")
        os.makedirs(profile_path, exist_ok=True)
        
        options_selenium = webdriver.ChromeOptions()
        
        # Profile
        options_selenium.add_argument(f"--user-data-dir={profile_path}")
        options_selenium.add_argument("--profile-directory=ScraperSession")
        
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
        
        # Create and add proxy extension
        proxy_ext_zip_path = create_proxy_extension(PROXY_URL)
        options_selenium.add_extension(proxy_ext_zip_path)
        print(f"[PROXY] Extension added: {proxy_ext_zip_path}")
        
        service = ChromeService(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options_selenium)
        
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
        print("Warning: undetected-chromedriver not installed, using standard selenium")
        print("Install with: pip install undetected-chromedriver")
        
        chrome_options = Options()
        # NO PROFILE - causes hangs/locks
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option("useAutomationExtension", False)
        chrome_options.add_argument("--no-first-run")
        chrome_options.add_argument("--no-default-browser-check")
        chrome_options.add_argument(f"--user-agent={user_agent}")
        
        # PROXY configuration
        if PROXY_URL:
            chrome_options.add_argument(f"--proxy-server={PROXY_URL}")
            print(f"Using proxy: {PROXY_URL}")
        
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
        
        # Apply stealth scripts on every page load
        apply_stealth_scripts(driver)
        
        # Random wait (human-like)
        time.sleep(random.uniform(2.5, 4.5))
        
        # Human-like scrolling behavior
        scroll_amount = random.randint(300, 700)
        driver.execute_script(f"window.scrollTo(0, {scroll_amount});")
        time.sleep(random.uniform(0.5, 1.5))
        
        # Simulate mouse movement
        human_like_mouse_movement(driver)
        
        # Scroll back up slowly
        driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(random.uniform(0.3, 0.8))
        
        # Check for IP block or CAPTCHA
        page_source = driver.page_source.lower()
        
        # Debug: show page title and snippet + save full HTML
        try:
            page_title = driver.title
            snippet = page_source[:500].replace('\n', ' ')[:200]
            print(f"  [DEBUG] Page title: {page_title}")
            print(f"  [DEBUG] Page snippet: {snippet}...")
            
            # Save full page to file for debugging
            with open("last_page_debug.html", "w", encoding="utf-8") as f:
                f.write(driver.page_source)
            print(f"  [DEBUG] Full page saved to: last_page_debug.html")
        except Exception as e:
            print(f"  [DEBUG] Error saving page: {e}")
        
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
                print(f"  [DEBUG] BLOCK DETECTED! Keyword: '{keyword}'")
                print("\n" + "="*60)
                print("[!] IP BLOCKED BY ALLEGRO!")
                print("="*60)
                print("Your IP has been blocked by Allegro's anti-bot protection.")
                print("This happens when scraping too fast or too many requests.")
                print("\nRECOMMENDATIONS:")
                print("1. Wait 30-60 minutes before retrying")
                print("2. Use VPN or change IP address")
                print("3. Reduce scraping speed (already set to 30-60s delay)")
                print("4. Reduce batch size (currently 3 offers)")
                print("5. Consider using different proxy or residential IP")
                print("="*60 + "\n")
                return None  # Return immediately, don't check for CAPTCHA
        
        # Check for CAPTCHA (including DataDome)
        captcha_detected = False
        try:
            # Check page source for CAPTCHA keywords
            if 'captcha-delivery' in page_source or 'datadome' in page_source:
                captcha_detected = True
            
            # Look for specific CAPTCHA elements
            if not captcha_detected:
                captcha_iframes = driver.find_elements(By.CSS_SELECTOR, "iframe[src*='captcha-delivery'], iframe[title*='captcha'], iframe[title*='DataDome']")
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
            print("[!] CAPTCHA DETECTED!")
            print("="*60)
            print("Please solve the CAPTCHA manually in the Chrome window.")
            print("The script will wait and continue automatically once solved.")
            print("="*60 + "\n")
            
            # Wait until CAPTCHA is solved
            captcha_start = time.time()
            while True:
                time.sleep(5)
                try:
                    # Check if we're still on CAPTCHA page
                    # Method 1: Check page title (CAPTCHA page has generic "allegro.pl" title)
                    current_title = driver.title.lower()
                    page_source_check = driver.page_source.lower()
                    
                    # CAPTCHA indicators
                    has_captcha_iframe = len(driver.find_elements(By.CSS_SELECTOR, "iframe[src*='captcha-delivery']")) > 0
                    has_captcha_text = "captcha-delivery" in page_source_check
                    is_generic_title = current_title.strip() == "allegro.pl"
                    
                    # If page has real content (not CAPTCHA), continue
                    if not has_captcha_iframe and not has_captcha_text and not is_generic_title:
                        elapsed = int(time.time() - captcha_start)
                        print(f"[OK] CAPTCHA solved after {elapsed}s! Page loaded: {driver.title[:50]}")
                        time.sleep(2)
                        break
                    else:
                        print(f"    Still waiting... (title: {current_title[:30]}, iframe: {has_captcha_iframe})")
                        
                    # Timeout after 5 minutes
                    if time.time() - captcha_start > 300:
                        print("[!] CAPTCHA timeout (5min) - skipping offer")
                        return None, None, None, None
                except Exception as e:
                    print(f"[!] Error checking CAPTCHA status: {e}")
                    break
        
        # Check for block page AFTER CAPTCHA solved
        page_source_after = driver.page_source.lower()
        block_keywords_check = [
            "zostałeś zablokowany",
            "you have been blocked",
            "zablokowano",
            "access denied",
            "dostęp zablokowany",
            "coś w zachowaniu twojej przeglądarki"
        ]
        
        for keyword in block_keywords_check:
            if keyword in page_source_after:
                print(f"\n  [!] ALLEGRO BLOCK PAGE detected after CAPTCHA!")
                print(f"  Block keyword found: '{keyword}'")
                print("\n" + "="*60)
                print("[!] IP BLOCKED BY ALLEGRO!")
                print("="*60)
                print("Allegro blocked your IP even after solving CAPTCHA.")
                print("Your IP: Check the block message for details")
                print("\nRECOMMENDATIONS:")
                print("1. Wait 1-2 hours before retrying")
                print("2. Use VPN or mobile hotspot (different IP)")
                print("3. This IP is flagged - switching required")
                print("="*60 + "\n")
                raise Exception("IP_BLOCKED_AFTER_CAPTCHA")
        
        # Wait for "Inne oferty" section to load
        time.sleep(3)
        
        html = driver.page_source
        
        # Parse JSON data embedded in page
        offers = []
        
        # Look for JSON with offer data
        json_pattern = r'"offers":\s*\[(.*?)\]'
        json_match = re.search(json_pattern, html, re.DOTALL)
        
        if json_match:
            try:
                offers_json = json_match.group(1)
                # Extract individual offers
                offer_pattern = r'\{[^}]*"price"[^}]*"amount":\s*"?(\d+(?:\.\d+)?)"?[^}]*"sellerLogin":\s*"([^"]+)"[^}]*\}'
                matches = re.findall(offer_pattern, offers_json)
                
                for price_str, seller in matches:
                    try:
                        price = Decimal(price_str.replace(',', '.'))
                        offers.append({
                            'price': price,
                            'seller': seller,
                            'url': offer_url,
                            'delivery_days': None
                        })
                    except:
                        continue
            except Exception as e:
                print(f"  JSON parse error: {e}")
        
        # Fallback: simple price extraction from HTML
        if not offers:
            price_pattern = r'data-price="(\d+(?:\.\d+)?)"|"amount":\s*"?(\d+(?:\.\d+)?)"?'
            price_matches = re.findall(price_pattern, html)
            
            for match in price_matches:
                price_str = match[0] or match[1]
                if price_str:
                    try:
                        price = Decimal(price_str.replace(',', '.'))
                        if price > 0:
                            offers.append({
                                'price': price,
                                'seller': 'Unknown',
                                'url': offer_url,
                                'delivery_days': None
                            })
                    except:
                        continue
        
        print(f"  Found {len(offers)} offers on page")
        
        if not offers:
            return {'status': 'no_offers', 'message': 'Nie znaleziono ofert konkurencji'}
        
        # Filter offers by delivery time (max 4 days) and price (cheaper than ours)
        my_price_decimal = Decimal(str(my_price).replace(',', '.'))
        
        print(f"  My price: {my_price_decimal}, filtering...")
        
        filtered_offers = []
        for offer in offers:
            # Skip if delivery time is known and > 4 days
            if offer['delivery_days'] is not None and offer['delivery_days'] > 4:
                continue
            
            # Skip if price >= our price
            if offer['price'] >= my_price_decimal:
                continue
            
            filtered_offers.append(offer)
        
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
            'delivery_days': cheapest['delivery_days']
        }
        
    except Exception as e:
        print(f"  Error checking offer: {e}")
        return None


def get_offers():
    """Fetch offers that need price checking from magazyn API."""
    try:
        url = f"{MAGAZYN_URL}/api/scraper/get_tasks"
        print(f"[API] Fetching offers from: {url}")
        response = requests.get(
            url,
            params={"limit": BATCH_SIZE},
            timeout=10
        )
        print(f"[API] Response status: {response.status_code}")
        response.raise_for_status()
        data = response.json()
        offers = data.get("offers", [])
        print(f"[API] Got {len(offers)} offers")
        return offers
    except Exception as e:
        print(f"[!] Error fetching offers: {e}")
        import traceback
        traceback.print_exc()
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
        print(f"Error submitting results: {e}")
        return False


def warm_up_session(driver):
    """Visit Allegro homepage first to establish cookies and look human."""
    print("[WARMUP] Visiting Allegro homepage first to establish session...")
    
    try:
        # Visit homepage
        driver.get("https://allegro.pl")
        time.sleep(random.uniform(3, 5))
        
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
    global MAGAZYN_URL, PROXY_URL, MOBILE_MODE
    
    parser = argparse.ArgumentParser(description="Allegro Competitor Price Checker")
    parser.add_argument("--url", required=True, help="Magazyn URL (e.g., https://magazyn.retrievershop.pl)")
    parser.add_argument("--interval", type=int, default=POLL_INTERVAL, help="Poll interval in seconds")
    parser.add_argument("--proxy", type=str, default=None, help="Proxy server (e.g., http://host:port or socks5://host:port)")
    parser.add_argument("--mobile", action="store_true", help="Use mobile user-agent and viewport")
    parser.add_argument("--no-warmup", action="store_true", help="Skip warmup (visit homepage first)")
    args = parser.parse_args()
    
    MAGAZYN_URL = args.url.rstrip("/")
    poll_interval = args.interval
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
            if not warm_up_session(driver):
                print("[!] Warmup failed - IP may be blocked")
                print("[!] Try using --proxy or wait and try again later")
                return
        
        
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
                        status = competitor_data.get('status')
                        
                        if status == 'competitor_cheaper':
                            print(f"       Competitor: {competitor_data['price']} zł ({competitor_data['seller']}) [OK]")
                            if competitor_data.get('delivery_days'):
                                print(f"       Delivery: {competitor_data['delivery_days']} days")
                            results.append({
                                "offer_id": offer_id,
                                "status": "competitor_cheaper",
                                "competitor_price": competitor_data['price'],
                                "competitor_seller": competitor_data['seller'],
                                "competitor_url": competitor_data['url'],
                                "competitor_delivery_days": competitor_data.get('delivery_days')
                            })
                        elif status == 'cheapest':
                            print(f"       [OK] Retriever_Shop najtanszy!")
                            results.append({
                                "offer_id": offer_id,
                                "status": "cheapest"
                            })
                        elif status == 'no_offers':
                            print(f"       [!] Brak ofert konkurencji")
                            results.append({
                                "offer_id": offer_id,
                                "status": "no_offers"
                            })
                    else:
                        print(f"       Error: no data returned")
                except Exception as e:
                    if "IP_BLOCKED" in str(e):
                        print("\n[!] Stopping scraper due to IP block")
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
