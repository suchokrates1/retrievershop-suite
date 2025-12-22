#!/usr/bin/env python3
"""
Local Allegro Scraper - uses Selenium with your real Brave profile
No captcha because it uses your existing session with cookies!

Usage: python local_scraper.py [offer_url]
"""
import sys
import time
import re
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# Paths
BRAVE_PATH = r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"
BRAVE_PROFILE = r"C:\Users\sucho\AppData\Local\BraveSoftware\Brave-Browser\User Data"

def create_driver():
    """Create Selenium driver using Brave with your profile"""
    options = Options()
    options.binary_location = BRAVE_PATH
    
    # Use your real profile with all cookies and session
    options.add_argument(f"--user-data-dir={BRAVE_PROFILE}")
    options.add_argument("--profile-directory=Default")
    
    # Disable automation detection
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    
    # Normal window (not headless - DataDome detects headless)
    options.add_argument("--start-maximized")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")
    
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    
    # Additional stealth
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": """
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
        """
    })
    
    return driver

def scrape_offer(driver, url):
    """Scrape single Allegro offer"""
    print(f"Loading: {url}")
    driver.get(url)
    
    # Wait for page load
    time.sleep(5)
    
    # Take screenshot
    screenshot_path = Path("allegro_offer_screenshot.png")
    driver.save_screenshot(str(screenshot_path))
    print(f"Screenshot saved: {screenshot_path}")
    
    # Check for captcha
    html = driver.page_source
    if "captcha-delivery.com" in html or "datadome" in html.lower():
        print("WARNING: CAPTCHA detected! Please solve it manually in the browser window...")
        input("Press Enter after solving captcha...")
        html = driver.page_source
    
    return html

def parse_price(html):
    """Extract price from Allegro HTML"""
    # Pattern 1: aria-label
    match = re.search(r'aria-label="(\d+[,\.]\d{2})\s*zł"', html)
    if match:
        return match.group(1)
    
    # Pattern 2: data-price
    match = re.search(r'data-price="(\d+\.?\d*)"', html)
    if match:
        return match.group(1)
    
    # Pattern 3: JSON-LD
    match = re.search(r'"price"\s*:\s*"?(\d+\.?\d*)"?', html)
    if match:
        return match.group(1)
    
    # Pattern 4: price span
    match = re.search(r'>(\d{1,3}(?:\s?\d{3})*[,\.]\d{2})\s*zł<', html)
    if match:
        return match.group(1).replace(" ", "")
    
    return None

def main():
    print("=" * 60)
    print("Local Allegro Scraper (Brave + Your Profile)")
    print("=" * 60)
    
    # Get URL from args or use default
    if len(sys.argv) > 1:
        url = sys.argv[1]
    else:
        url = "https://allegro.pl/oferta/17892897249"
    
    print("\nStarting Brave with your profile...")
    print("(This will open a new Brave window)")
    
    driver = None
    try:
        driver = create_driver()
        print("OK: Brave started")
        
        html = scrape_offer(driver, url)
        print(f"Got HTML ({len(html)} bytes)")
        
        # Save for debugging
        Path("allegro_offer.html").write_text(html, encoding="utf-8")
        
        # Parse price
        price = parse_price(html)
        if price:
            print(f"\nOK: Price: {price} zl")
        else:
            print("\nWARNING: Could not find price")
            
        # Keep browser open for inspection
        print("\nBrowser stays open for inspection.")
        input("Press Enter to close browser...")
        
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if driver:
            driver.quit()

if __name__ == "__main__":
    main()
