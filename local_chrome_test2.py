#!/usr/bin/env python3
"""Test Chrome z profilem BEZ headless"""
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import time

url = "https://allegro.pl/oferta/szelki-dla-psa-truelove-front-line-premium-xl-granatowe-18180401323"

print(f"[LOG] URL: {url}")
print(f"[LOG] Starting Chrome with profile (NO headless)...")

profile_path = r"C:\Users\sucho\retrievershop-suite\allegro_scraper_profile"

options = Options()
options.add_argument(f'--user-data-dir={profile_path}')
# options.add_argument('--headless=new')  # DISABLED!
options.add_argument('--no-sandbox')
options.add_argument('--disable-dev-shm-usage')
options.add_argument('--window-size=1920,1080')
# Anti-detection
options.add_argument('--disable-blink-features=AutomationControlled')
options.add_experimental_option('excludeSwitches', ['enable-automation'])
options.add_experimental_option('useAutomationExtension', False)

driver = webdriver.Chrome(options=options)
driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
    'source': 'Object.defineProperty(navigator, "webdriver", {get: () => undefined})'
})

try:
    print(f"[LOG] Loading page...")
    driver.get(url)
    time.sleep(8)
    
    print(f"[LOG] Page title: {driver.title}")
    
    html = driver.page_source
    print(f"[LOG] HTML length: {len(html)}")
    print(f"[LOG] Has DataDome: {'captcha-delivery.com' in html}")
    print(f"[LOG] Has listing: {'__listing_StoreState' in html}")
    
    # Scroll down to inne-oferty
    print(f"[LOG] Scrolling...")
    driver.execute_script("window.scrollTo(0, 3000);")
    time.sleep(3)
    
    html = driver.page_source
    print(f"[LOG] After scroll: {len(html)}")
    print(f"[LOG] Has listing: {'__listing_StoreState' in html}")
    
    with open(r"C:\Users\sucho\retrievershop-suite\chrome_test2.html", "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[LOG] Saved to chrome_test2.html!")
    
finally:
    driver.quit()
