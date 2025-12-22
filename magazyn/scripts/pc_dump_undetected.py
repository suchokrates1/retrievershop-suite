import json
import os
import time
from pathlib import Path


def read_allegro_cookies():
    cookies_path = os.environ.get("ALLEGRO_COOKIES_FILE")
    if not cookies_path:
        return []
    path = Path(cookies_path)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def fetch_with_undetected(offer_url: str, cookies_data, proxy: str | None):
    import undetected_chromedriver as uc
    
    options = uc.ChromeOptions()
    options.add_argument("--window-size=1280,900")
    options.add_argument("--lang=pl-PL")
    options.add_argument("--disable-blink-features=AutomationControlled")
    
    # Disable images for faster loading
    prefs = {"profile.managed_default_content_settings.images": 2}
    options.add_experimental_option("prefs", prefs)
    
    if proxy:
        options.add_argument(f"--proxy-server={proxy}")
        print(f"undetected_using_proxy {proxy}")
    
    print("undetected_starting_chrome")
    driver = uc.Chrome(
        options=options,
        use_subprocess=False,
    )
    
    try:
        driver.set_page_load_timeout(120)
        
        # Step 1: Load Allegro homepage
        print("undetected_loading allegro.pl")
        driver.get("https://allegro.pl/")
        print("undetected_loaded allegro.pl")
        time.sleep(2)
        driver.save_screenshot("/tmp/price_check_step1_home.png")
        print("saved_screenshot /tmp/price_check_step1_home.png")
        
        # Step 2: Add cookies
        if cookies_data:
            for c in cookies_data:
                name = c.get("name")
                value = c.get("value")
                if not name or value is None:
                    continue
                
                cookie = {
                    "name": name,
                    "value": value,
                    "domain": c.get("domain", ".allegro.pl").lstrip("."),
                    "path": c.get("path", "/"),
                }
                
                if "secure" in c:
                    cookie["secure"] = c["secure"]
                if "httpOnly" in c:
                    cookie["httpOnly"] = c["httpOnly"]
                if "expiry" in c:
                    cookie["expiry"] = c["expiry"]
                
                try:
                    driver.add_cookie(cookie)
                except Exception as e:
                    print(f"cookie_error {name}: {e}")
            
            print(f"undetected_added_cookies {len(cookies_data)}")
        
        time.sleep(1)
        driver.save_screenshot("/tmp/price_check_step2_cookies.png")
        print("saved_screenshot /tmp/price_check_step2_cookies.png")
        
        # Step 3: Load offer page
        print(f"undetected_loading offer {offer_url}")
        driver.get(offer_url)
        print("undetected_loaded offer")
        time.sleep(3)
        driver.save_screenshot("/tmp/price_check_step3_offer.png")
        print("saved_screenshot /tmp/price_check_step3_offer.png")
        
        # Human-like scrolling
        print("undetected_scrolling")
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight * 0.5);")
        time.sleep(2)
        driver.save_screenshot("/tmp/price_check_step4_scroll_mid.png")
        print("saved_screenshot /tmp/price_check_step4_scroll_mid.png")
        
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight * 0.9);")
        time.sleep(2)
        driver.save_screenshot("/tmp/price_check_step5_scroll_bottom.png")
        print("saved_screenshot /tmp/price_check_step5_scroll_bottom.png")
        
        driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(1)
        
        # Final screenshot and HTML
        driver.save_screenshot("/tmp/price_check_shot.png")
        print("saved_screenshot /tmp/price_check_shot.png")
        
        return driver.page_source
        
    finally:
        driver.quit()


def main():
    offer_url = "https://allegro.pl/oferta/17892897249"
    cookies_data = read_allegro_cookies()
    proxy = os.environ.get("ALLEGRO_PROXY_URL")
    
    try:
        html = fetch_with_undetected(offer_url, cookies_data, proxy)
        if html:
            with open("/tmp/price_check_offer.html", "w", encoding="utf-8") as f:
                f.write(html)
            print("saved_html /tmp/price_check_offer.html via undetected")
    except Exception as exc:
        print("undetected_error", exc)
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
