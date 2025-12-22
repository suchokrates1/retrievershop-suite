import base64
import json
import os
import re
import time
from pathlib import Path

import requests


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


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-User": "?1",
    "Sec-Fetch-Dest": "document",
    "Pragma": "no-cache",
    "Cache-Control": "no-cache",
    "Referer": "https://allegro.pl/",
}


def load_allegro_cookies(session: requests.Session) -> None:
    for c in read_allegro_cookies():
        try:
            session.cookies.set(
                c.get("name"),
                c.get("value"),
                domain=c.get("domain"),
                path=c.get("path", "/"),
            )
        except Exception:
            continue


def fetch_with_selenium(offer_url: str, cookies_data, proxy: str | None, record_steps: bool = False):
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service

    opts = Options()
    headless = os.environ.get("ALLEGRO_HEADLESS", "1").lower() not in {"0", "false", "no"}
    remote_debug_port = os.environ.get("ALLEGRO_REMOTE_DEBUG_PORT", "")
    
    # Use Xvfb virtual display if remote debugging is enabled
    if remote_debug_port:
        os.environ['DISPLAY'] = ':99'
        # Start Xvfb in background
        import subprocess
        try:
            subprocess.Popen(['Xvfb', ':99', '-screen', '0', '1280x900x24'], 
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(2)  # Wait for Xvfb to start
            print("selenium_xvfb_started")
        except Exception as e:
            print(f"selenium_xvfb_failed {e}")
    elif headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument(f"--user-agent={HEADERS['User-Agent']}")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--window-size=1280,900")
    opts.add_argument("--lang=pl-PL")
    opts.add_argument("--blink-settings=imagesEnabled=false")  # Disable images for faster loading
    if os.environ.get("ALLEGRO_DISABLE_JS", "").lower() in {"1", "true", "yes"}:
        opts.add_experimental_option("prefs", {"profile.managed_default_content_settings.javascript": 2})
        print("selenium_javascript_disabled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    if remote_debug_port:
        opts.add_argument(f"--remote-debugging-port={remote_debug_port}")
        opts.add_argument("--remote-debugging-address=0.0.0.0")
        opts.add_argument("--remote-allow-origins=*")
        print(f"selenium_remote_debug_port {remote_debug_port}")
    if proxy:
        opts.add_argument(f"--proxy-server={proxy}")
        print(f"selenium_using_proxy {proxy}")

    driver = webdriver.Chrome(service=Service("/usr/bin/chromedriver"), options=opts)
    try:
        driver.set_page_load_timeout(180)  # 3 minutes for slow SOCKS proxy
        driver.execute_cdp_cmd("Network.enable", {})
        driver.execute_cdp_cmd(
            "Network.setExtraHTTPHeaders",
            {
                "headers": {
                    "Accept-Language": HEADERS["Accept-Language"],
                    "Referer": HEADERS["Referer"],
                }
            },
        )
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {
                "source": (
                    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
                    "Object.defineProperty(navigator, 'languages', {get: () => ['pl-PL','pl','en-US']});"
                    "Object.defineProperty(navigator, 'platform', {get: () => 'Win32'});"
                )
            },
        )
        print("selenium_loading allegro.pl")
        driver.get("https://allegro.pl/")
        print("selenium_loaded allegro.pl")
        if record_steps:
            snap_path = "/tmp/price_check_step1_home.png"
            try:
                driver.get_screenshot_as_file(snap_path)
                print("saved_screenshot", snap_path)
            except Exception:
                pass
        for c in cookies_data:
            name = c.get("name")
            value = c.get("value")
            if not name or value is None:
                continue
            cd = {"name": name, "value": value, "path": c.get("path", "/")}
            domain = c.get("domain")
            if domain:
                cd["domain"] = domain.lstrip(".")
            if isinstance(c.get("secure"), bool):
                cd["secure"] = c.get("secure")
            if isinstance(c.get("expiry"), int):
                cd["expiry"] = c.get("expiry")
            try:
                driver.add_cookie(cd)
            except Exception:
                continue
        time.sleep(1.0)
        if record_steps:
            snap_path = "/tmp/price_check_step2_cookies.png"
            try:
                driver.get_screenshot_as_file(snap_path)
                print("saved_screenshot", snap_path)
            except Exception:
                pass
        print(f"selenium_loading offer {offer_url}")
        driver.get(offer_url)
        print("selenium_loaded offer")
        time.sleep(3)
        if record_steps:
            snap_path = "/tmp/price_check_step3_offer.png"
            try:
                driver.get_screenshot_as_file(snap_path)
                print("saved_screenshot", snap_path)
            except Exception:
                pass
        
        # If remote debugging is enabled, give time for manual captcha solving
        debug_port = os.environ.get("ALLEGRO_REMOTE_DEBUG_PORT")
        print(f"selenium_checking_remote_debug debug_port={debug_port}")
        if debug_port:
            print("selenium_waiting_30min_for_manual_captcha_solving")
            print("Connect via: chrome://inspect in your browser")
            print(f"Or open: http://localhost:{debug_port} in VS Code Simple Browser")
            print("Waiting for 1800 seconds...")
            for i in range(180):
                time.sleep(10)
                if i % 6 == 0:  # Print every minute
                    print(f"Still waiting... {(i+1)*10}/1800 seconds elapsed")
            print("Wait complete, continuing...")
        # simple human-like scrolling
        try:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight * 0.5);")
            time.sleep(2)
            if record_steps:
                snap_path = "/tmp/price_check_step4_scroll_mid.png"
                driver.get_screenshot_as_file(snap_path)
                print("saved_screenshot", snap_path)
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight * 0.9);")
            time.sleep(2)
            if record_steps:
                snap_path = "/tmp/price_check_step5_scroll_bottom.png"
                driver.get_screenshot_as_file(snap_path)
                print("saved_screenshot", snap_path)
            driver.execute_script("window.scrollTo(0, 0);")
            time.sleep(1)
        except Exception:
            pass

        time.sleep(3)
        shot_path = "/tmp/price_check_shot.png"
        try:
            driver.get_screenshot_as_file(shot_path)
            print("saved_screenshot", shot_path)
        except Exception:
            pass
        return driver.page_source
    finally:
        driver.quit()


def main():
    s = requests.Session()
    cookies_data = read_allegro_cookies()
    for c in cookies_data:
        try:
            s.cookies.set(
                c.get("name"),
                c.get("value"),
                domain=c.get("domain"),
                path=c.get("path", "/"),
            )
        except Exception:
            continue
    login = s.get("http://localhost:8000/login", timeout=8)
    m = re.search(r"name=\"csrf_token\" type=\"hidden\" value=\"([^\"]+)\"", login.text)
    if not m:
        print("missing csrf")
        return
    csrf = m.group(1)
    s.post(
        "http://localhost:8000/login",
        data={"username": "admin", "password": "admin123", "csrf_token": csrf},
        timeout=8,
        allow_redirects=True,
    )

    start = time.time()
    r = s.get(
        "http://localhost:8000/allegro/price-check/stream",
        stream=True,
        timeout=(5, 60),
    )

    screenshot_saved = False
    offer_url = None
    count = 0
    for line in r.iter_lines(decode_unicode=True):
        if not line:
            continue
        count += 1
        if time.time() - start > 45 or count > 200:
            break
        if not line.startswith("data: "):
            continue
        try:
            payload = json.loads(line[len("data: "):])
        except Exception:
            continue
        if isinstance(payload, dict):
            if (
                not offer_url
                and isinstance(payload.get("value"), str)
                and "https://allegro.pl/oferta/" in payload.get("value", "")
            ):
                try:
                    offer_url = json.loads(payload["value"]).get("url")
                except Exception:
                    pass
            if "image" in payload and not screenshot_saved:
                with open("/tmp/price_check_shot.png", "wb") as f:
                    f.write(base64.b64decode(payload["image"]))
                screenshot_saved = True
                print(f"saved_screenshot /tmp/price_check_shot.png t={time.time()-start:.1f}s")
                break

    if not offer_url:
        offer_url = "https://allegro.pl/oferta/17892897249"
    proxy = os.environ.get("ALLEGRO_PROXY_URL")
    html_saved = False
    try:
        html = fetch_with_selenium(offer_url, cookies_data, proxy, record_steps=True)
        if html:
            with open("/tmp/price_check_offer.html", "w", encoding="utf-8") as f:
                f.write(html)
            html_saved = True
            print("saved_html /tmp/price_check_offer.html via selenium")
    except Exception as exc:
        print("selenium_error", exc)

    if not html_saved:
        try:
            proxies = {"http": proxy, "https": proxy} if proxy else {}
            try:
                html = s.get(offer_url, timeout=60, headers=HEADERS, proxies=proxies).text
            except Exception:
                html = s.get(offer_url, timeout=60, headers=HEADERS, proxies={}).text
            with open("/tmp/price_check_offer.html", "w", encoding="utf-8") as f:
                f.write(html)
            print("saved_html /tmp/price_check_offer.html")
        except Exception as exc:
            print("html_error", exc)


if __name__ == "__main__":
    main()
