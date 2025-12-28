"""
Test Playwright + Firefox przez Tor SOCKS5 proxy
"""
from playwright.sync_api import sync_playwright
import time

def test_allegro_tor():
    with sync_playwright() as p:
        browser = p.firefox.launch(
            headless=False,
            proxy={
                "server": "socks5://127.0.0.1:9050"
            },
            firefox_user_prefs={
                "dom.webdriver.enabled": False,
            }
        )
        
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            locale="pl-PL",
            timezone_id="Europe/Warsaw",
        )
        
        page = context.new_page()
        
        # Test IP
        print("Checking IP through Tor...")
        page.goto("https://ipinfo.io/json", timeout=60000)
        print(f"IP Info: {page.content()}")
        
        print("\nOpening Allegro...")
        try:
            page.goto("https://allegro.pl", timeout=60000)
            time.sleep(3)
            
            content = page.content().lower()
            if "zostałeś zablokowany" in content:
                print("[!] BLOCKED!")
            elif "captcha" in content or "datadome" in content:
                print("[!] CAPTCHA - solve it manually")
                input("Press Enter after solving...")
            else:
                print("[OK] Homepage loaded!")
                print(f"Title: {page.title()}")
        except Exception as e:
            print(f"Error: {e}")
        
        input("Press Enter to close...")
        browser.close()

if __name__ == "__main__":
    test_allegro_tor()
