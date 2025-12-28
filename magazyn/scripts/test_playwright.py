"""
Quick test: Playwright + Firefox vs DataDome
"""
from playwright.sync_api import sync_playwright
import time
import random

def test_allegro():
    with sync_playwright() as p:
        # Firefox is harder to fingerprint than Chrome
        browser = p.firefox.launch(
            headless=False,  # Visible for debugging
            firefox_user_prefs={
                "dom.webdriver.enabled": False,
                "useAutomationExtension": False,
            }
        )
        
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            locale="pl-PL",
            timezone_id="Europe/Warsaw",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:134.0) Gecko/20100101 Firefox/134.0",
        )
        
        page = context.new_page()
        
        print("Opening Allegro homepage...")
        page.goto("https://allegro.pl")
        time.sleep(random.uniform(3, 5))
        
        # Check for block
        content = page.content().lower()
        if "zostałeś zablokowany" in content:
            print("[!] BLOCKED on homepage!")
            page.screenshot(path="blocked_homepage.png")
        else:
            print("[OK] Homepage loaded")
            
            # Try an offer page
            print("Trying offer page...")
            page.goto("https://allegro.pl/oferta/17785658907")
            time.sleep(random.uniform(3, 5))
            
            content = page.content().lower()
            if "zostałeś zablokowany" in content:
                print("[!] BLOCKED on offer page!")
                page.screenshot(path="blocked_offer.png")
            elif "captcha" in content or "datadome" in content:
                print("[!] CAPTCHA detected - solve it manually")
                input("Press Enter after solving CAPTCHA...")
            else:
                print("[OK] Offer page loaded!")
                page.screenshot(path="success_offer.png")
                print(f"Title: {page.title()}")
        
        input("Press Enter to close browser...")
        browser.close()

if __name__ == "__main__":
    test_allegro()
