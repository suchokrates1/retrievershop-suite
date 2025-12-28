"""
Test Playwright + Firefox przez Tor - bezpośrednio Allegro
"""
from playwright.sync_api import sync_playwright
import time

def test_allegro_tor():
    with sync_playwright() as p:
        browser = p.firefox.launch(
            headless=False,
            proxy={
                "server": "socks5://127.0.0.1:9050"
            }
        )
        
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            locale="pl-PL",
            timezone_id="Europe/Warsaw",
        )
        
        page = context.new_page()
        
        print("Opening Allegro directly...")
        try:
            page.goto("https://allegro.pl", timeout=120000)  # 2 min timeout
            time.sleep(5)
            
            content = page.content().lower()
            title = page.title()
            print(f"Title: {title}")
            
            if "zostałeś zablokowany" in content:
                print("[!] BLOCKED!")
                page.screenshot(path="tor_blocked.png")
            elif "captcha" in content or "datadome" in content:
                print("[!] CAPTCHA - solve manually")
                input("Press Enter after solving...")
            else:
                print("[OK] Allegro loaded!")
                page.screenshot(path="tor_success.png")
        except Exception as e:
            print(f"Error: {e}")
            page.screenshot(path="tor_error.png")
        
        input("Press Enter to close browser...")
        browser.close()

if __name__ == "__main__":
    test_allegro_tor()
