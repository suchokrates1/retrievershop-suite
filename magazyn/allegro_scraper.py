"""Utilities for scraping Allegro offer pages with Selenium."""

from __future__ import annotations

import contextvars
import logging
import os
import re
import shutil
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Callable, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)


_LOG_CALLBACK: "contextvars.ContextVar[Optional[Callable[[str], None]]]" = contextvars.ContextVar(
    "allegro_scraper_log_callback",
    default=None,
)


class AllegroScrapeError(RuntimeError):
    """Raised when scraping Allegro listings fails and carries Selenium logs."""

    def __init__(self, message: str, logs: Sequence[str]):
        super().__init__(message)
        self.logs = list(logs)

try:  # pragma: no cover - optional dependency during import time
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait
except ImportError:  # pragma: no cover - handled at runtime
    webdriver = None  # type: ignore[assignment]
    Options = None  # type: ignore[assignment]
    By = None  # type: ignore[assignment]
    Service = None  # type: ignore[assignment]
    EC = None  # type: ignore[assignment]
    WebDriverWait = None  # type: ignore[assignment]


@dataclass(slots=True)
class Offer:
    """Representation of a competitor offer scraped from Allegro."""

    title: str
    price: str
    seller: str
    url: str


def _require_selenium() -> None:
    if webdriver is None or Options is None or By is None or EC is None or WebDriverWait is None:
        raise RuntimeError(
            "Selenium is required to scrape Allegro listings. "
            "Install the 'selenium' package and ensure a Chrome/Chromium driver is available."
        )


def _log_step(logs: Optional[List[str]], message: str) -> None:
    """Record a Selenium interaction both in-memory and in application logs."""

    if logger.isEnabledFor(logging.DEBUG):
        logger.debug("[Selenium] %s", message)
    if logs is not None:
        logs.append(message)
    callback = _LOG_CALLBACK.get()
    if callback is not None:
        try:
            callback(message)
        except Exception:  # pragma: no cover - defensive logging
            logger.exception("Selenium log callback failed", exc_info=True)


def _find_chromedriver() -> Optional[str]:
    """Return a path to a ChromeDriver binary if one is available."""

    env_path = os.environ.get("CHROMEDRIVER_PATH")
    if env_path:
        return env_path

    detected = shutil.which("chromedriver")
    if detected:
        return detected

    common_paths = (
        "/usr/bin/chromedriver",
        "/usr/lib/chromium-browser/chromedriver",
        "/usr/lib/chromium/chromedriver",
    )
    for candidate in common_paths:
        if os.path.exists(candidate):
            return candidate
    return None


def _mk_driver(headless: bool = True, logs: Optional[List[str]] = None) -> "webdriver.Chrome":
    _require_selenium()
    opts = Options()
    if os.path.exists("/usr/bin/chromium"):
        opts.binary_location = "/usr/bin/chromium"
    if headless:
        opts.add_argument("--headless=new")
        _log_step(logs, "Uruchamianie ChromeDriver w trybie headless")
    else:
        _log_step(logs, "Uruchamianie ChromeDriver z widocznym oknem")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1365,900")
    opts.add_argument("--lang=pl-PL")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--disable-features=IsolateOrigins,site-per-process")
    opts.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
    opts.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
    opts.add_experimental_option("useAutomationExtension", False)
    driver_kwargs = {"options": opts}

    driver_path = _find_chromedriver()
    if driver_path and Service is not None:
        logger.debug("Using ChromeDriver binary at %s", driver_path)
        _log_step(logs, f"Używany chromedriver: {driver_path}")
        driver_kwargs["service"] = Service(executable_path=driver_path)
    driver = webdriver.Chrome(**driver_kwargs)
    try:
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {
                "source": (
                    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
                    "window.chrome = {runtime: {}};"
                    "Object.defineProperty(navigator, 'languages', {get: () => ['pl-PL', 'pl']});"
                    "Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3]});"
                )
            },
        )
    except Exception:  # pragma: no cover - depends on CDP support
        _log_step(logs, "Nie udało się zastosować ustawień anty-bot w CDP")
    return driver


def _click_any(
    driver: "webdriver.Chrome",
    xpaths: Sequence[str],
    wait: int = 8,
    logs: Optional[List[str]] = None,
) -> bool:
    for xp in xpaths:
        try:
            _log_step(logs, f"Oczekiwanie na element do kliknięcia: {xp}")
            element = WebDriverWait(driver, wait).until(EC.element_to_be_clickable((By.XPATH, xp)))
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", element)
            time.sleep(0.15)
            element.click()
            _log_step(logs, f"Kliknięto element: {xp}")
            return True
        except Exception:  # pragma: no cover - defensive, depends on live DOM
            _log_step(logs, f"Nie udało się kliknąć elementu: {xp}")
            continue
    return False


def _dismiss_overlays(driver: "webdriver.Chrome", logs: Optional[List[str]] = None) -> None:
    labels = [
        "Przejdź do serwisu",
        "Akceptuj",
        "Zgadzam",
        "OK",
        "Rozumiem",
        "Zamknij",
        "Akceptuję",
        "Przejdź dalej",
        "Kontynuuj",
    ]
    xpath_variants = [
        "//button[contains(@data-role,'accept')]",
        "//button[contains(@id,'accept')]",
        "//button[contains(@class,'accept')]",
        "//a[contains(@class,'dismiss')]",
        "//button[contains(@class,'rodo')]",
    ]
    frames = [None]
    try:
        frames.extend(driver.find_elements(By.TAG_NAME, "iframe"))
    except Exception:  # pragma: no cover - iframe enumeration may fail silently
        pass

    for frame in frames:
        try:
            if frame is not None:
                try:
                    driver.switch_to.frame(frame)
                except Exception:
                    continue
            for text in labels:
                try:
                    for button in driver.find_elements(By.XPATH, f"//button[contains(., '{text}')]"):
                        if button.is_displayed():
                            button.click()
                            _log_step(logs, f"Zamknięto baner przyciskiem: {text}")
                            time.sleep(0.1)
                except Exception:
                    continue
            for xp in xpath_variants:
                try:
                    for el in driver.find_elements(By.XPATH, xp):
                        if el.is_displayed():
                            el.click()
                            _log_step(logs, f"Zamknięto overlay selektorem: {xp}")
                            time.sleep(0.1)
                except Exception:
                    continue
        finally:
            driver.switch_to.default_content()

    for selector in [
        "//div[contains(@class,'overlay')]//button[contains(@class,'close')]",
        "//button[contains(@aria-label,'zamknij') or contains(@aria-label,'Zamknij')]",
    ]:
        try:
            for el in driver.find_elements(By.XPATH, selector):
                if el.is_displayed():
                    el.click()
                    _log_step(logs, f"Zamknięto overlay po kliknięciu: {selector}")
                    time.sleep(0.1)
        except Exception:
            continue


def _extract_price(text: str) -> str:
    clean = (text or "").replace("\xa0", " ")
    match = re.search(r"\d[\d\s.,]*\s*zł", clean)
    if match:
        return match.group(0).strip()
    clean = clean.strip()
    return clean or "(brak ceny)"


def _locate_listing(driver: "webdriver.Chrome"):
    containers = driver.find_elements(By.CSS_SELECTOR, "div.opbox-sheet-wrapper, div[class*='opbox-sheet']")
    for container in containers:
        try:
            listing = container.find_element(By.CSS_SELECTOR, "div[data-box-name='ProductListingContent']")
            if listing.is_displayed():
                return listing
        except Exception:
            continue
    return None


def _wait_for_listing(driver: "webdriver.Chrome", logs: Optional[List[str]] = None):
    _log_step(logs, "Oczekiwanie na arkusz z ofertami konkurencji")
    listing = WebDriverWait(driver, 18).until(lambda d: _locate_listing(d) or False)
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'start'});", listing)
    except Exception:  # pragma: no cover - scroll failures ignored
        pass
    return listing


def _wait_for_offers(driver: "webdriver.Chrome", logs: Optional[List[str]] = None):
    def _offers(drv: "webdriver.Chrome"):
        listing = _locate_listing(drv)
        if listing is None:
            return False
        rows = listing.find_elements(
            By.XPATH,
            ".//article[.//a[contains(@href,'/oferta/')]] | "
            ".//div[.//a[contains(@href,'/oferta/')]]",
        )
        visible = [row for row in rows if row.is_displayed()]
        return visible if visible else False

    _log_step(logs, "Oczekiwanie na pojawienie się co najmniej jednej oferty")
    return WebDriverWait(driver, 18).until(_offers)


def _detect_antibot_screen(driver: "webdriver.Chrome", logs: Optional[List[str]] = None) -> None:
    try:
        body_text = driver.find_element(By.TAG_NAME, "body").text.lower()
    except Exception:
        body_text = ""
    patterns = [
        "wyglądasz jak bot",
        "zabezpieczamy się przed botami",
        "captcha",
        "ochrona kupujących",
    ]
    if any(pattern in body_text for pattern in patterns):
        message = "Wykryto ekran anty-botowy Allegro, przerwano skanowanie"
        _log_step(logs, message)
        raise RuntimeError(message)


def _find_cheapest_link(driver: "webdriver.Chrome"):
    selectors = [
        "a[data-analytics-click-label='cheapest'][href='#inne-oferty-produktu']",
        "a[class*='other-offers-link-cheapest'][href='#inne-oferty-produktu']",
    ]
    for selector in selectors:
        try:
            for element in driver.find_elements(By.CSS_SELECTOR, selector):
                if element.is_displayed():
                    return element
        except Exception:
            continue
    return None


def parse_price_amount(price_text: str) -> Optional[Decimal]:
    """Return the numeric value encoded in a scraped price string."""

    if not price_text:
        return None
    text = price_text.replace("\xa0", " ")
    text = re.sub(r"[^0-9,\.]+", "", text)
    if not text:
        return None
    text = text.replace(",", ".")
    if text.count(".") > 1:
        integer, _, fractional = text.partition(".")
        fractional = fractional.replace(".", "")
        text = f"{integer}.{fractional}"
    try:
        return Decimal(text).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None


def fetch_competitors(
    product_url: str,
    *,
    stop_seller: Optional[str] = None,
    limit: int = 30,
    headless: bool = True,
    log_callback: Optional[Callable[[str], None]] = None,
) -> Tuple[List[Offer], List[str]]:
    """Scrape competitor offers displayed on an Allegro product page."""

    logs: List[str] = []
    token = _LOG_CALLBACK.set(log_callback) if log_callback is not None else None
    try:
        _log_step(logs, f"Inicjalizacja Selenium dla URL: {product_url}")
        driver = _mk_driver(headless=headless, logs=logs)
        try:
            _log_step(logs, f"Przejście na stronę produktu: {product_url}")
            driver.get(product_url)
            time.sleep(1.5)
            _dismiss_overlays(driver, logs=logs)
            _detect_antibot_screen(driver, logs=logs)

            link = _find_cheapest_link(driver)
            clicked = False
            if link is not None:
                try:
                    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", link)
                except Exception:  # pragma: no cover - scroll failures ignored
                    pass
                time.sleep(0.2)
                try:
                    driver.execute_script("arguments[0].focus();", link)
                except Exception:  # pragma: no cover - focus may fail silently
                    pass
                try:
                    link.click()
                    clicked = True
                    _log_step(logs, "Kliknięto odnośnik 'Najtańsze'")
                except Exception:
                    _log_step(logs, "Bezpośrednie kliknięcie odnośnika 'Najtańsze' nie powiodło się")

            if not clicked:
                clicked = _click_any(
                    driver,
                    [
                        "//div[.//text()[contains(., 'Najtańsze')]]//ancestor::a[@href='#inne-oferty-produktu']",
                        "//div[.//text()[contains(., 'Najtańsze')]]//ancestor::button",
                        "//a[contains(@class,'other-offers-link-cheapest') and @href='#inne-oferty-produktu']",
                        "//a[.//text()[contains(., 'WSZYSTKIE OFERTY')]]",
                        "//button[.//text()[contains(., 'WSZYSTKIE OFERTY')]]",
                        "//a[contains(., 'Inne oferty produktu') or contains(., 'Wszystkie oferty')]",
                    ],
                    logs=logs,
                )
            if not clicked:
                logs.append("Nie znaleziono odnośnika do sekcji 'Najtańsze' ani alternatywnych ofert.")
                return [], logs

            try:
                section = driver.find_element(By.CSS_SELECTOR, "#inne-oferty-produktu")
                driver.execute_script("arguments[0].scrollIntoView({block:'start'});", section)
            except Exception:
                pass

            _dismiss_overlays(driver, logs=logs)
            _detect_antibot_screen(driver, logs=logs)

            listing = _wait_for_listing(driver, logs=logs)
            try:
                if not listing.is_displayed():
                    _dismiss_overlays(driver, logs=logs)
            except Exception:
                _dismiss_overlays(driver, logs=logs)
            rows = _wait_for_offers(driver, logs=logs)
            _log_step(logs, f"Liczba znalezionych wierszy w arkuszu: {len(rows)}")
            offers: List[Offer] = []
            seen: set[str] = set()

            for row in rows:
                try:
                    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", row)
                except Exception:  # pragma: no cover - scroll failures ignored
                    pass
                time.sleep(0.05)

                anchor = None
                try:
                    anchor = row.find_element(By.XPATH, ".//a[contains(@href,'/oferta/')]")
                except Exception:
                    try:
                        href = row.get_attribute("href")
                        if href and "/oferta/" in href:
                            anchor = row
                    except Exception:  # pragma: no cover - defensive
                        anchor = None
                if anchor is None:
                    continue

                href = anchor.get_attribute("href") or ""
                if not href or "/oferta/" not in href:
                    continue
                if href.startswith("//"):
                    href = f"https:{href}"
                elif href.startswith("/"):
                    href = f"https://allegro.pl{href}"
                if href in seen:
                    continue
                seen.add(href)

                title = anchor.text.strip() or "(brak tytułu)"
                if title == "(brak tytułu)":
                    try:
                        title = row.find_element(By.XPATH, ".//h2|.//h3|.//h4").text.strip()
                    except Exception:  # pragma: no cover - fallback
                        pass

                price_text = ""
                for px in (
                    ".//*[@data-role='price']",
                    ".//*[@data-testid='price']",
                    ".//*[contains(@class,'price')]",
                    ".//*[@aria-label and contains(@aria-label,'zł')]",
                    ".//*[@data-price]",
                    ".//*[@data-analytics-interaction-label='price']",
                    ".//*[@data-analytics-interaction-label and contains(@data-analytics-interaction-label,'price')]",
                    ".//span[contains(text(),'zł')]",
                    ".//div[contains(text(),'zł')]",
                ):
                    try:
                        price_text = row.find_element(By.XPATH, px).text.strip()
                        if price_text:
                            break
                    except Exception:
                        continue
                if not price_text:
                    for attr in ("aria-label", "data-analytics-click-label", "data-analytics-interaction-label"):
                        try:
                            value = anchor.get_attribute(attr) or ""
                            if "zł" in value:
                                price_text = value
                                break
                        except Exception:
                            continue
                price = _extract_price(price_text)

                seller_text = ""
                for sx in (
                    ".//*[@data-role='seller-name']",
                    ".//*[@data-testid='seller-name']",
                    ".//*[@data-analytics-interaction-label='sellerName']",
                    ".//*[@data-analytics-click-label='sellerName']",
                    ".//*[contains(@class,'seller') or contains(.,'Poleca sprzedający')]/..",
                    ".//*[contains(., 'Poleca sprzedający')]",
                    ".//a[contains(@href, '/uzytkownik/') or contains(@href, '/strefa_sprzedawcy/')]",
                    ".//a[contains(@data-analytics-interaction-label,'sellerProfile')]",
                    ".//*[@aria-label and contains(@aria-label,'sprzedaw')]",
                ):
                    try:
                        st = row.find_element(By.XPATH, sx).text.strip()
                        if st:
                            seller_text = st
                            break
                    except Exception:
                        continue
                if not seller_text:
                    try:
                        seller_text = anchor.get_attribute("data-analytics-seller-name") or ""
                    except Exception:
                        seller_text = ""
                if not seller_text:
                    try:
                        seller_text = anchor.get_attribute("data-seller-name") or ""
                    except Exception:
                        seller_text = ""

                seller_clean = re.sub(r"\s*Poleca.*$", "", seller_text).strip()
                seller_clean = re.sub(r"\s+Firma.*$", "", seller_clean).strip()
                seller_clean = re.sub(r"\s+Oficjalny sklep.*$", "", seller_clean).strip()

                # zbieraj oferty do momentu trafienia wskazanego sprzedawcy; jego już nie dodawaj
                if stop_seller and seller_clean.lower() == stop_seller.lower():
                    _log_step(logs, f"Zatrzymano na sprzedawcy: {seller_clean}")
                    break

                offers.append(Offer(title=title, price=price, seller=seller_clean or seller_text, url=href))
                _log_step(
                    logs,
                    "Znaleziono ofertę konkurencji: "
                    f"tytuł='{title}', cena='{price}', sprzedawca='{seller_clean or seller_text}'",
                )
                if len(offers) >= limit:
                    _log_step(logs, f"Osiągnięto limit {limit} ofert, zakończenie skanowania")
                    break

            return offers, logs
        except Exception as exc:
            _log_step(logs, f"Błąd Selenium: {exc}")
            raise AllegroScrapeError(str(exc), logs) from exc
        finally:
            _log_step(logs, "Zamykanie przeglądarki Selenium")
            driver.quit()
    finally:
        if token is not None:
            _LOG_CALLBACK.reset(token)


def fetch_competitors_for_offer(
    offer_id: str,
    *,
    stop_seller: Optional[str] = None,
    limit: int = 30,
    headless: bool = True,
    log_callback: Optional[Callable[[str], None]] = None,
) -> Tuple[List[Offer], List[str]]:
    """Convenience wrapper for :func:`fetch_competitors` using an offer identifier."""

    product_url = f"https://allegro.pl/oferta/{offer_id}"
    return fetch_competitors(
        product_url,
        stop_seller=stop_seller,
        limit=limit,
        headless=headless,
        log_callback=log_callback,
    )


__all__ = [
    "Offer",
    "fetch_competitors",
    "fetch_competitors_for_offer",
    "parse_price_amount",
]
