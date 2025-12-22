#!/usr/bin/env python3
"""
Allegro Price Check API Server
Runs locally on your PC, listens for requests from RPI to scrape Allegro

Usage: python scraper_api.py
Then RPI can call: http://192.168.31.150:5555/check_price?url=https://allegro.pl/oferta/123
"""
import sys
import time
import re
from pathlib import Path
from datetime import datetime
from flask import Flask, request, jsonify
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager

app = Flask(__name__)

# Paths - use dedicated Chrome profile for scraping
SCRIPT_DIR = Path(__file__).parent
CHROME_PROFILE_DIR = SCRIPT_DIR / "allegro_scraper_profile"

# Global driver (reuse between requests)
driver = None

def create_driver():
    """Create Selenium driver using Chrome with dedicated profile"""
    options = Options()
    
    # Use dedicated profile for scraping (doesn't interfere with daily browsing)
    CHROME_PROFILE_DIR.mkdir(exist_ok=True)
    options.add_argument(f"--user-data-dir={CHROME_PROFILE_DIR}")
    options.add_argument("--profile-directory=Default")
    
    # Disable automation detection
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    
    # Normal window
    options.add_argument("--start-maximized")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")
    
    service = Service(ChromeDriverManager().install())
    d = webdriver.Chrome(service=service, options=options)
    
    # Additional stealth
    d.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": """
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
        """
    })
    
    return d

def get_driver():
    """Get or create driver"""
    global driver
    if driver is None:
        print("Creating new Brave driver...")
        driver = create_driver()
    return driver

def parse_price(html):
    """Extract price from Allegro HTML"""
    # Pattern 1: aria-label
    match = re.search(r'aria-label="(\d+[,\.]\d{2})\s*zl"', html)
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
    match = re.search(r'>(\d{1,3}(?:\s?\d{3})*[,\.]\d{2})\s*zl<', html)
    if match:
        return match.group(1).replace(" ", "")
    
    return None

@app.route('/check_price', methods=['GET'])
def check_price():
    """Check price for given Allegro URL or EAN"""
    url = request.args.get('url')
    ean = request.args.get('ean')
    
    if not url and not ean:
        return jsonify({"error": "Missing 'url' or 'ean' parameter"}), 400
    
    try:
        d = get_driver()
        
        # If EAN provided, search for it first
        if ean:
            print(f"Searching for EAN: {ean}")
            search_url = f"https://allegro.pl/listing?string={ean}"
            d.get(search_url)
            time.sleep(3)
            
            # Find cheapest offer on search results
            html = d.page_source
            
            # Extract offers from search results
            import re
            # Pattern for price in search results
            prices = re.findall(r'data-price="(\d+\.?\d*)"', html)
            if prices:
                min_price = min(float(p) for p in prices)
                
                # Save HTML for debugging
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                html_file = Path(f"scraped_ean_{ean}_{timestamp}.html")
                html_file.write_text(html, encoding="utf-8")
                
                return jsonify({
                    "success": True,
                    "ean": ean,
                    "price": f"{min_price:.2f}",
                    "timestamp": timestamp,
                    "html_saved": str(html_file)
                })
            else:
                return jsonify({
                    "error": "No offers found for EAN",
                    "ean": ean
                }), 404
        
        # Otherwise use URL
        if "allegro.pl" not in url:
            return jsonify({"error": "Invalid Allegro URL"}), 400
            
        print(f"Loading: {url}")
        d.get(url)
        time.sleep(5)  # Wait for page load
        
        html = d.page_source
        
        # Check for captcha
        if "captcha-delivery.com" in html:
            return jsonify({
                "error": "CAPTCHA detected",
                "message": "Please solve captcha manually in Chrome window and retry"
            }), 503
        
        # Parse price
        price = parse_price(html)
        
        if price:
            # Save HTML for debugging
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            html_file = Path(f"scraped_{timestamp}.html")
            html_file.write_text(html, encoding="utf-8")
            
            return jsonify({
                "success": True,
                "url": url,
                "price": price,
                "timestamp": timestamp,
                "html_saved": str(html_file)
            })
        else:
            return jsonify({
                "error": "Price not found",
                "html_length": len(html)
            }), 404
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/check_prices_batch', methods=['POST'])
def check_prices_batch():
    """Check prices for multiple EANs in batch"""
    data = request.get_json()
    if not data or 'eans' not in data:
        return jsonify({"error": "Missing 'eans' in request body"}), 400
    
    eans = data['eans']
    if not isinstance(eans, list):
        return jsonify({"error": "'eans' must be a list"}), 400
    
    results = []
    
    try:
        d = get_driver()
        
        for ean in eans:
            print(f"Searching for EAN: {ean}")
            
            try:
                search_url = f"https://allegro.pl/listing?string={ean}"
                d.get(search_url)
                time.sleep(3)
                
                html = d.page_source
                
                # Check for captcha
                if "captcha-delivery.com" in html:
                    results.append({
                        "ean": ean,
                        "error": "CAPTCHA detected",
                        "price": None
                    })
                    continue
                
                # Extract prices from search results
                import re
                prices = re.findall(r'data-price="(\d+\.?\d*)"', html)
                
                if prices:
                    min_price = min(float(p) for p in prices)
                    results.append({
                        "ean": ean,
                        "price": f"{min_price:.2f}",
                        "error": None
                    })
                else:
                    results.append({
                        "ean": ean,
                        "price": None,
                        "error": "No offers found"
                    })
                    
            except Exception as e:
                results.append({
                    "ean": ean,
                    "price": None,
                    "error": str(e)
                })
        
        return jsonify({
            "success": True,
            "results": results,
            "total": len(eans),
            "found": sum(1 for r in results if r.get('price'))
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/status', methods=['GET'])
def status():
    """Check if scraper is running"""
    return jsonify({
        "status": "running",
        "driver_active": driver is not None
    })

@app.route('/restart', methods=['POST'])
def restart():
    """Restart driver (e.g., after solving captcha)"""
    global driver
    if driver:
        driver.quit()
        driver = None
    return jsonify({"status": "driver restarted"})

if __name__ == "__main__":
    print("=" * 60)
    print("Allegro Scraper API Server")
    print("=" * 60)
    print("\nStarting server on http://0.0.0.0:5555")
    print("RPI can call: http://192.168.31.150:5555/check_price?url=...")
    print("\nEndpoints:")
    print("  GET  /check_price?url=<allegro_url>  - Check price")
    print("  GET  /status                         - Server status")
    print("  POST /restart                        - Restart driver")
    print("\nPress Ctrl+C to stop")
    print("=" * 60)
    
    app.run(host='0.0.0.0', port=5555, debug=False)
