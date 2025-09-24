"""Utilities for scraping Allegro offer pages with Selenium."""

from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

try:  # pragma: no cover - optional dependency during import time
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait
except ImportError:  # pragma: no cover - handled at runtime
    webdriver = None  # type: ignore[assignment]
    Options = None  # type: ignore[assignment]
    By = None  # type: ignore[assignment]
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


def _mk_driver(headless: bool = True) -> "webdriver.Chrome":
    _require_selenium()
    opts = Options()
    if os.path.exists("/usr/bin/chromium"):
        opts.binary_location = "/usr/bin/chromium"
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1280,1600")
    opts.add_argument("--lang=pl-PL")
    return webdriver.Chrome(options=opts)


def _click_any(driver: "webdriver.Chrome", xpaths: Sequence[str], wait: int = 8) -> bool:
    for xp in xpaths:
        try:
            element = WebDriverWait(driver, wait).until(EC.element_to_be_clickable((By.XPATH, xp)))
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", element)
            time.sleep(0.15)
            element.click()
            return True
        except Exception:  # pragma: no cover - defensive, depends on live DOM
            continue
    return False


def _accept_cookies(driver: "webdriver.Chrome") -> None:
    labels = [
        "Przejdź do serwisu",
        "Akceptuj",
        "Zgadzam",
        "OK",
        "Rozumiem",
        "Zamknij",
        "Akceptuję",
    ]
    for text in labels:
        try:
            for button in driver.find_elements(By.XPATH, f"//button[contains(., '{text}')]"):
                if button.is_displayed():
                    button.click()
                    time.sleep(0.1)
        except Exception:  # pragma: no cover - depends on cookie banners
            continue


def _extract_price(text: str) -> str:
    clean = (text or "").replace("\xa0", " ")
    match = re.search(r"\d[\d\s.,]*\s*zł", clean)
    if match:
        return match.group(0).strip()
    clean = clean.strip()
    return clean or "(brak ceny)"


def _wait_modal(driver: "webdriver.Chrome") -> None:
    try:
        WebDriverWait(driver, 12).until(
            EC.presence_of_element_located(
                (
                    By.XPATH,
                    "//div[@role='dialog'] | "
                    "//section[.//text()[contains(., 'Inne oferty produktu')]]",
                )
            )
        )
    except Exception:  # pragma: no cover - depends on live DOM timing
        pass
    time.sleep(0.6)


def _rows_in_modal(driver: "webdriver.Chrome"):
    rows = driver.find_elements(By.XPATH, "//div[@role='dialog']//article | //div[@role='dialog']//li")
    if not rows:
        rows = driver.find_elements(By.XPATH, "//div[@role='dialog']//a[contains(@href,'/oferta/')]")
    return rows


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
) -> Tuple[List[Offer], List[str]]:
    """Scrape competitor offers displayed on an Allegro product page."""

    logs: List[str] = []
    driver = _mk_driver(headless=headless)
    try:
        driver.get(product_url)
        time.sleep(1.5)
        _accept_cookies(driver)

        clicked = _click_any(
            driver,
            [
                "//div[.//text()[contains(., 'Najtańsze')]]//ancestor::button",
                "//div[.//text()[contains(., 'Najtańsze')]]//ancestor::a",
                "//button[.//text()[contains(., 'Najtańsze')]]",
            ],
        )
        if not clicked:
            clicked = _click_any(
                driver,
                [
                    "//a[.//text()[contains(., 'WSZYSTKIE OFERTY')]]",
                    "//button[.//text()[contains(., 'WSZYSTKIE OFERTY')]]",
                    "//a[contains(., 'Inne oferty produktu') or contains(., 'Wszystkie oferty')]",
                ],
            )
        if not clicked:
            logs.append("Nie znaleziono 'Najtańsze' ani 'WSZYSTKIE OFERTY'.")
            return [], logs

        _wait_modal(driver)
        offers: List[Offer] = []
        rows = _rows_in_modal(driver)
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
                ".//span[contains(@class,'price')]",
                ".//div[contains(@class,'price')]",
                ".//*[contains(text(),'zł')]",
            ):
                try:
                    price_text = row.find_element(By.XPATH, px).text.strip()
                    if price_text:
                        break
                except Exception:
                    continue
            price = _extract_price(price_text)

            seller_text = ""
            for sx in (
                ".//*[contains(@class,'seller') or contains(.,'Poleca sprzedający')]/..",
                ".//*[contains(., 'Poleca sprzedający')]",
                ".//a[contains(@href, '/uzytkownik/') or contains(@href, '/strefa_sprzedawcy/')]"):
                try:
                    seller_text = row.find_element(By.XPATH, sx).text.strip()
                    if seller_text:
                        break
                except Exception:
                    continue

            seller_clean = re.sub(r"\s*Poleca.*$", "", seller_text).strip()
            seller_clean = re.sub(r"\s+Firma.*$", "", seller_clean).strip()
            seller_clean = re.sub(r"\s+Oficjalny sklep.*$", "", seller_clean).strip()

            if stop_seller and seller_clean.lower() == stop_seller.lower():
                logs.append(f"Pominięto ofertę sprzedawcy: {seller_clean}")
                continue

            offers.append(Offer(title=title, price=price, seller=seller_clean or seller_text, url=href))
            if len(offers) >= limit:
                break

        return offers, logs
    finally:
        driver.quit()


def fetch_competitors_for_offer(
    offer_id: str,
    *,
    stop_seller: Optional[str] = None,
    limit: int = 30,
    headless: bool = True,
) -> Tuple[List[Offer], List[str]]:
    """Convenience wrapper for :func:`fetch_competitors` using an offer identifier."""

    product_url = f"https://allegro.pl/oferta/{offer_id}"
    return fetch_competitors(
        product_url,
        stop_seller=stop_seller,
        limit=limit,
        headless=headless,
    )


__all__ = [
    "Offer",
    "fetch_competitors",
    "fetch_competitors_for_offer",
    "parse_price_amount",
]

