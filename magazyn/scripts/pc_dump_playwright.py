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


def fetch_with_playwright(offer_url: str, cookies_data, proxy: str | None, remote_debug_port: int = 0):
    """
    Fetch page using Playwright with stealth mode and optional remote debugging.
    
    Args:
        offer_url: URL to fetch
        cookies_data: List of cookie dicts
        proxy: Proxy URL (e.g., socks5://host:port)
        remote_debug_port: If >0, starts Chrome with remote debugging on this port
    """
    from playwright.sync_api import sync_playwright
    
    proxy_config = None
    if proxy:
        # Parse proxy URL
        if proxy.startswith("socks5://"):
            server = proxy.replace("socks5://", "")
            proxy_config = {"server": f"socks5://{server}"}
        elif proxy.startswith("http://") or proxy.startswith("https://"):
            proxy_config = {"server": proxy}
        print(f"playwright_using_proxy {proxy}")
    else:
        print("playwright_no_proxy direct_connection")
    
    with sync_playwright() as p:
        # Launch args for stealth
        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-features=IsolateOrigins,site-per-process",
            "--disable-web-security",
            "--disable-features=VizDisplayCompositor",
            "--lang=pl-PL",
        ]
        
        # Add remote debugging if requested
        if remote_debug_port > 0:
            launch_args.append(f"--remote-debugging-port={remote_debug_port}")
            print(f"playwright_remote_debug http://localhost:{remote_debug_port}")
        
        # Disable images for faster loading
        launch_args.append("--blink-settings=imagesEnabled=false")
        
        headless = os.environ.get("ALLEGRO_HEADLESS", "1").lower() not in {"0", "false", "no"}
        
        browser = p.chromium.launch(
            headless=headless,
            args=launch_args,
            proxy=proxy_config,
        )
        
        try:
            # Create context with stealth settings
            context = browser.new_context(
                viewport={"width": 1280, "height": 900},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                locale="pl-PL",
                timezone_id="Europe/Warsaw",
                permissions=["geolocation"],
                geolocation={"latitude": 52.2297, "longitude": 21.0122},  # Warsaw
                color_scheme="light",
                extra_http_headers={
                    "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                    "Sec-Fetch-Site": "none",
                    "Sec-Fetch-Mode": "navigate",
                    "Sec-Fetch-User": "?1",
                    "Sec-Fetch-Dest": "document",
                },
            )
            
            # Add stealth scripts
            context.add_init_script("""
                // Overwrite the `navigator.webdriver` property
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined,
                });
                
                // Overwrite the `navigator.languages` property
                Object.defineProperty(navigator, 'languages', {
                    get: () => ['pl-PL', 'pl', 'en-US', 'en'],
                });
                
                // Overwrite the `navigator.platform` property
                Object.defineProperty(navigator, 'platform', {
                    get: () => 'Win32',
                });
                
                // Overwrite the `navigator.plugins` length
                Object.defineProperty(navigator, 'plugins', {
                    get: () => [1, 2, 3, 4, 5],
                });
                
                // Pass chrome checks
                window.chrome = {
                    runtime: {},
                };
                
                // Pass permissions check
                const originalQuery = window.navigator.permissions.query;
                window.navigator.permissions.query = (parameters) => (
                    parameters.name === 'notifications' ?
                        Promise.resolve({ state: Notification.permission }) :
                        originalQuery(parameters)
                );
            """)
            
            page = context.new_page()
            page.set_default_timeout(120000)  # 120s timeout
            
            # Step 1: Load Allegro homepage
            print("playwright_loading allegro.pl")
            page.goto("https://allegro.pl/", wait_until="domcontentloaded")
            print("playwright_loaded allegro.pl")
            page.screenshot(path="/tmp/price_check_step1_home.png")
            print("saved_screenshot /tmp/price_check_step1_home.png")
            
            # Step 2: Add cookies
            if cookies_data:
                playwright_cookies = []
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
                    if "sameSite" in c:
                        cookie["sameSite"] = c["sameSite"]
                    if "expires" in c or "expiry" in c:
                        exp = c.get("expires") or c.get("expiry")
                        if isinstance(exp, (int, float)):
                            cookie["expires"] = exp
                    
                    playwright_cookies.append(cookie)
                
                context.add_cookies(playwright_cookies)
                print(f"playwright_added_cookies {len(playwright_cookies)}")
            
            time.sleep(1)
            page.screenshot(path="/tmp/price_check_step2_cookies.png")
            print("saved_screenshot /tmp/price_check_step2_cookies.png")
            
            # Step 3: Load offer page
            print(f"playwright_loading offer {offer_url}")
            page.goto(offer_url, wait_until="domcontentloaded")
            print("playwright_loaded offer")
            time.sleep(3)
            page.screenshot(path="/tmp/price_check_step3_offer.png")
            print("saved_screenshot /tmp/price_check_step3_offer.png")
            
            # Human-like scrolling
            print("playwright_scrolling")
            page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.5)")
            time.sleep(2)
            page.screenshot(path="/tmp/price_check_step4_scroll_mid.png")
            print("saved_screenshot /tmp/price_check_step4_scroll_mid.png")
            
            page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.9)")
            time.sleep(2)
            page.screenshot(path="/tmp/price_check_step5_scroll_bottom.png")
            print("saved_screenshot /tmp/price_check_step5_scroll_bottom.png")
            
            page.evaluate("window.scrollTo(0, 0)")
            time.sleep(1)
            
            # If remote debugging is enabled, wait for manual intervention
            if remote_debug_port > 0:
                print(f"playwright_waiting_for_manual_intervention (press Enter in terminal when done)")
                input()  # Wait for user to solve captcha manually
            
            # Final screenshot and HTML
            page.screenshot(path="/tmp/price_check_shot.png")
            print("saved_screenshot /tmp/price_check_shot.png")
            
            html = page.content()
            return html
            
        finally:
            browser.close()


def main():
    offer_url = "https://allegro.pl/oferta/17892897249"
    cookies_data = read_allegro_cookies()
    proxy = os.environ.get("ALLEGRO_PROXY_URL")
    remote_debug = int(os.environ.get("ALLEGRO_REMOTE_DEBUG_PORT", "0"))
    
    try:
        html = fetch_with_playwright(offer_url, cookies_data, proxy, remote_debug)
        if html:
            with open("/tmp/price_check_offer.html", "w", encoding="utf-8") as f:
                f.write(html)
            print("saved_html /tmp/price_check_offer.html via playwright")
    except Exception as exc:
        print("playwright_error", exc)
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
