"""
Allegro Price Scraper - Polling Worker

This script runs as a background worker that:
1. Polls magazyn API for scraping tasks
2. Searches Allegro for prices
3. Submits results back to magazyn

Usage:
    python scraper_worker.py --url https://magazyn.retrievershop.pl

The scraper uses Chrome with a dedicated profile (allegro_scraper_profile/)
to bypass DataDome bot detection.
"""

import os
import sys
import time
import re
import argparse
import requests
from decimal import Decimal
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager


# Configuration
MAGAZYN_URL = None  # Will be set from command line
POLL_INTERVAL = 30  # seconds between polls
BATCH_SIZE = 10  # max tasks per batch
CHROME_PROFILE_DIR = Path(__file__).parent / "allegro_scraper_profile"


def setup_chrome_driver():
    """Initialize Chrome with dedicated profile."""
    chrome_options = Options()
    
    # Use dedicated profile directory
    CHROME_PROFILE_DIR.mkdir(exist_ok=True)
    chrome_options.add_argument(f"--user-data-dir={CHROME_PROFILE_DIR.absolute()}")
    chrome_options.add_argument("--profile-directory=Default")
    
    # Not headless - we need real browser to bypass DataDome
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


def search_allegro_price(driver, ean):
    """
    Search Allegro for EAN and return lowest price.
    
    Returns:
        (price, url) or (None, error_message)
    """
    try:
        search_url = f"https://allegro.pl/listing?string={ean}"
        driver.get(search_url)
        
        # Wait for page load
        time.sleep(3)
        
        # Check for CAPTCHA
        if "captcha" in driver.page_source.lower() or "datadome" in driver.page_source.lower():
            print("\n⚠️  CAPTCHA DETECTED! Please solve it manually in the browser...")
            print("    Waiting for you to solve it...")
            
            # Wait until CAPTCHA is solved (check every 5 seconds)
            while True:
                time.sleep(5)
                if "captcha" not in driver.page_source.lower() and "datadome" not in driver.page_source.lower():
                    print("✓ CAPTCHA solved! Continuing...\n")
                    time.sleep(2)  # Extra wait after CAPTCHA
                    break
        
        html = driver.page_source
        
        # Try multiple price patterns
        patterns = [
            r'"price":{"amount":"([\d.]+)"',  # JSON in page
            r'"price":([\d.]+)',  # Simple JSON
            r'<meta\s+itemprop="price"\s+content="([\d.]+)"',  # Meta tag
            r'data-price="([\d.]+)"',  # Data attribute
            r'aria-label="[^"]*?([\d]+[,.]\d{2})\s*zł"',  # Aria label
        ]
        
        all_matches = []
        for pattern in patterns:
            matches = re.findall(pattern, html)
            all_matches.extend(matches)
        
        if not all_matches:
            return None, "No prices found"
        
        # Convert to Decimal (handle both . and , as decimal separator)
        prices = []
        for match in all_matches:
            try:
                # Replace comma with dot
                price_str = match.replace(',', '.')
                prices.append(Decimal(price_str))
            except:
                continue
        
        if not prices:
            return None, "Could not parse prices"
        
        min_price = min(prices)
        return str(min_price), search_url
        
    except Exception as e:
        return None, str(e)


def get_tasks():
    """Fetch pending tasks from magazyn API."""
    try:
        response = requests.get(
            f"{MAGAZYN_URL}/api/scraper/get_tasks",
            params={"limit": BATCH_SIZE},
            timeout=10
        )
        response.raise_for_status()
        data = response.json()
        return data.get("tasks", [])
    except Exception as e:
        print(f"Error fetching tasks: {e}")
        return []


def submit_results(results):
    """Submit results to magazyn API."""
    try:
        response = requests.post(
            f"{MAGAZYN_URL}/api/scraper/submit_results",
            json={"results": results},
            timeout=30
        )
        response.raise_for_status()
        data = response.json()
        print(f"✓ Submitted {data.get('processed', 0)} results")
        return True
    except Exception as e:
        print(f"Error submitting results: {e}")
        return False


def main():
    global MAGAZYN_URL
    
    parser = argparse.ArgumentParser(description="Allegro Price Scraper Worker")
    parser.add_argument("--url", required=True, help="Magazyn URL (e.g., https://magazyn.retrievershop.pl)")
    parser.add_argument("--interval", type=int, default=POLL_INTERVAL, help="Poll interval in seconds")
    args = parser.parse_args()
    
    MAGAZYN_URL = args.url.rstrip("/")
    poll_interval = args.interval
    
    print(f"Starting scraper worker...")
    print(f"Magazyn URL: {MAGAZYN_URL}")
    print(f"Poll interval: {poll_interval}s")
    print(f"Chrome profile: {CHROME_PROFILE_DIR}/")
    print()
    
    driver = None
    
    try:
        driver = setup_chrome_driver()
        print("✓ Chrome driver initialized")
        print()
        
        while True:
            tasks = get_tasks()
            
            if not tasks:
                print(f"No tasks. Waiting {poll_interval}s...")
                time.sleep(poll_interval)
                continue
            
            print(f"Processing {len(tasks)} tasks...")
            results = []
            
            for task in tasks:
                task_id = task["id"]
                ean = task["ean"]
                
                print(f"  Task {task_id}: EAN {ean}...", end=" ")
                
                price, url_or_error = search_allegro_price(driver, ean)
                
                if price:
                    print(f"✓ {price} zł")
                    results.append({
                        "id": task_id,
                        "price": price,
                        "url": url_or_error
                    })
                else:
                    print(f"✗ {url_or_error}")
                    results.append({
                        "id": task_id,
                        "error": url_or_error
                    })
            
            # Submit results
            submit_results(results)
            print()
            
    except KeyboardInterrupt:
        print("\nShutting down...")
    except Exception as e:
        print(f"Fatal error: {e}")
    finally:
        if driver:
            driver.quit()


if __name__ == "__main__":
    main()
