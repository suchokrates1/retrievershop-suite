"""Scraper i matching katalogu TipTop24 (Shoper) do ProductSize.

HTTP scraping jest domyslna sciezka. Live probe / trudniejsze strony
mozna odpalic przez CDP kontenera ``price-checker-chrome`` na minipc
(jak scraper cen Allegro).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse

import requests
from sqlalchemy.orm import Session

from magazyn.constants import SIZE_ALIASES, normalize_size_token
from magazyn.models.products import Product, ProductSize
from magazyn.models.tiptop import TipTopProduct, TipTopProductLink, TipTopVariant
from magazyn.services.product_matching import (
    _extract_category,
    _extract_model_series,
    _normalize_name,
)

logger = logging.getLogger(__name__)

TIPTOP_BASE = "https://tiptop24.pl"
TIPTOP_SEARCH_URL = f"{TIPTOP_BASE}/pl/s"
# Search endpoint often returns empty SSR; scrape Truelove from category pages.
TIPTOP_CATEGORY_URLS = (
    f"{TIPTOP_BASE}/dla-psa/szelki-dla-psa",
    f"{TIPTOP_BASE}/dla-psa/smycz-dla-psa",
    f"{TIPTOP_BASE}/dla-psa/obroza-dla-psa",
    f"{TIPTOP_BASE}/dla-psa/kamizelki-kapoki-i-kurtki-dla-psa",
    f"{TIPTOP_BASE}/dla-psa/pasy-biodrowe-do-biegania-z-psem",
    f"{TIPTOP_BASE}/dla-psa/saszetki-treningowe-na-przysmaki-dla-psa",
    f"{TIPTOP_BASE}/dla-psa/akcesoria-dla-wlascicieli-psow",
)
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (compatible; RetrieverShopMagazyn/1.0; +https://retrievershop.pl)"
)
BASKET_API_PATH = "/webapi/front/pl_PL/basket/PLN/"



@dataclass
class ParsedOption:
    option_id: int
    label: str
    values: list[tuple[int, str]] = field(default_factory=list)


@dataclass
class ParsedProductPage:
    tiptop_product_id: int
    url: str
    name: str
    producer: str | None
    price: float | None
    options: list[ParsedOption]
    size_option_id: int | None = None
    color_option_id: int | None = None


@dataclass
class CatalogSyncResult:
    products_upserted: int = 0
    variants_upserted: int = 0
    links_created: int = 0
    links_updated: int = 0
    errors: list[str] = field(default_factory=list)


def _normalize_color(value: str | None) -> str:
    if not value:
        return ""
    text = value.strip().lower()
    # TipTop sometimes uses "granatowy" etc.
    aliases = {
        "granatowy": "niebieski",
        "bananowy": "żółty",
        "bananowe": "żółty",
        "liliowy": "fioletowy",
        "liliowe": "fioletowy",
        "khaki": "zielony",
    }
    return aliases.get(text, text)


def _normalize_size_label(value: str | None) -> str:
    if not value:
        return ""
    token = value.strip().upper().replace(" ", "")
    # TipTop uses XXXS/XXS/3XS etc.
    tiptop_aliases = {
        "XXXS": "3XS",
        "XXS": "2XS",
        "2XS": "2XS",
        "3XS": "3XS",
        "4XL": "4XL",
        "XXL": "2XL",
        "XXXL": "3XL",
        "S/M": "S/M",
        "L/XL": "L/XL",
    }
    if token in tiptop_aliases:
        return tiptop_aliases[token]
    mapped = SIZE_ALIASES.get(token, token)
    canonical = normalize_size_token(mapped)
    return canonical or mapped


def _colors_match(a: str, b: str) -> bool:
    ca, cb = _normalize_color(a), _normalize_color(b)
    if not ca or not cb:
        return True
    if ca in cb or cb in ca:
        return True
    return ca[:4] == cb[:4]


def _sizes_match(a: str, b: str) -> bool:
    sa, sb = _normalize_size_label(a), _normalize_size_label(b)
    if not sa or not sb:
        return False
    return sa == sb


def _parse_price(text: str | None) -> float | None:
    if not text:
        return None
    cleaned = text.replace("\xa0", " ").replace("zł", "").strip()
    cleaned = cleaned.replace(" ", "").replace(",", ".")
    m = re.search(r"(\d+(?:\.\d+)?)", cleaned)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def parse_product_page(html: str, url: str) -> ParsedProductPage:
    """Parse TipTop/Shoper product HTML into structured options."""
    name_m = re.search(
        r'<h1[^>]*class="[^"]*product[^"]*"[^>]*>(.*?)</h1>|<h1[^>]*>(.*?)</h1>',
        html,
        re.I | re.S,
    )
    name = ""
    if name_m:
        name = re.sub(r"<[^>]+>", "", name_m.group(1) or name_m.group(2) or "").strip()
    if not name:
        title_m = re.search(r"<title>([^<]+)</title>", html, re.I)
        if title_m:
            name = title_m.group(1).split("–")[0].split("-")[0].strip()

    stock_m = re.search(
        r'OptionCurrentStock\s*=\s*"(\d+)"|'
        r'name="stock_id"[^>]*value="(\d+)"|'
        r'value="(\d+)"[^>]*name="stock_id"|'
        r'data-product-id="(\d+)"',
        html,
        re.I,
    )
    if not stock_m:
        raise ValueError(f"Nie znaleziono stock_id/product_id na stronie {url}")
    tiptop_product_id = int(
        next(g for g in stock_m.groups() if g)
    )

    producer_m = re.search(
        r'Producent:\s*</[^>]+>\s*<[^>]+>([^<]+)|'
        r'itemprop="brand"[^>]*content="([^"]+)"|'
        r'data-producer="([^"]+)"',
        html,
        re.I,
    )
    producer = None
    if producer_m:
        producer = next(g for g in producer_m.groups() if g).strip()

    price_m = re.search(
        r'itemprop="price"[^>]*content="([^"]+)"|'
        r'Cena:\s*</[^>]+>\s*<[^>]*>\s*([\d\s,]+)\s*zł',
        html,
        re.I | re.S,
    )
    price = None
    if price_m:
        price = _parse_price(next(g for g in price_m.groups() if g))

    options: list[ParsedOption] = []
    for sel in re.finditer(
        r'<select[^>]*\bid="option_(\d+)"[^>]*>(.*?)</select>',
        html,
        re.I | re.S,
    ):
        option_id = int(sel.group(1))
        body = sel.group(2)
        # Find label for this option
        label_m = re.search(
            rf'for="option_{option_id}"[^>]*>(.*?)</label>',
            html,
            re.I | re.S,
        )
        label = ""
        if label_m:
            label = re.sub(r"<[^>]+>", "", label_m.group(1)).strip().lower()
        values: list[tuple[int, str]] = []
        for opt in re.finditer(
            r'<option[^>]*\bvalue="(\d+)"[^>]*>(.*?)</option>',
            body,
            re.I | re.S,
        ):
            vid = int(opt.group(1))
            vlabel = re.sub(r"<[^>]+>", "", opt.group(2)).strip()
            if vlabel.lower() in {"wybierz", "select", ""}:
                continue
            values.append((vid, vlabel))
        if values:
            options.append(ParsedOption(option_id=option_id, label=label, values=values))

    size_option_id = None
    color_option_id = None
    for opt in options:
        lab = opt.label.lower()
        if any(k in lab for k in ("rozmiar", "size", "długość", "dlugosc", "szerokość", "szerokosc")):
            if size_option_id is None:
                size_option_id = opt.option_id
        if "kolor" in lab or "color" in lab:
            color_option_id = opt.option_id
    # Heuristic fallback: first select=size, select with color class / second=color
    if size_option_id is None and options:
        size_option_id = options[0].option_id
    if color_option_id is None and len(options) >= 2:
        color_option_id = options[1].option_id

    return ParsedProductPage(
        tiptop_product_id=tiptop_product_id,
        url=url,
        name=name,
        producer=producer,
        price=price,
        options=options,
        size_option_id=size_option_id,
        color_option_id=color_option_id,
    )


def expand_variants(parsed: ParsedProductPage) -> list[dict[str, Any]]:
    """Cartesian product of size × color options into TipTop cart payloads."""
    size_opt = next(
        (o for o in parsed.options if o.option_id == parsed.size_option_id), None
    )
    color_opt = next(
        (o for o in parsed.options if o.option_id == parsed.color_option_id), None
    )

    sizes = size_opt.values if size_opt else [(None, None)]
    colors = color_opt.values if color_opt else [(None, None)]

    variants: list[dict[str, Any]] = []
    for size_id, size_label in sizes:
        for color_id, color_label in colors:
            option_map: dict[str, int] = {}
            if size_opt and size_id is not None:
                option_map[str(size_opt.option_id)] = int(size_id)
            if color_opt and color_id is not None:
                option_map[str(color_opt.option_id)] = int(color_id)
            variants.append(
                {
                    "option_map": option_map,
                    "size_label": size_label,
                    "color_label": color_label,
                    "price": parsed.price,
                    "available": True,
                }
            )
    if not variants:
        variants.append(
            {
                "option_map": {},
                "size_label": None,
                "color_label": None,
                "price": parsed.price,
                "available": True,
            }
        )
    return variants


def extract_product_links_from_listing(html: str, base_url: str = TIPTOP_BASE) -> list[str]:
    """Extract TipTop product detail URLs from a category/listing page."""
    urls: list[str] = []
    seen: set[str] = set()

    def _maybe_add(href: str) -> None:
        if not href:
            return
        full = urljoin(base_url, href.split("#")[0].split("?")[0])
        path = urlparse(full).path.rstrip("/")
        lower = path.lower()
        if "truelove" not in lower:
            return
        if any(
            skip in lower
            for skip in (
                "/basket",
                "/cart",
                "/login",
                "/register",
                "/blog",
                "/producer/",
                "/producent/",
            )
        ):
            return
        # Skip collection/model index pages
        if "/modele/" in lower or lower.endswith("-modele"):
            return
        parts = [p for p in path.split("/") if p]
        # Product cards are usually /dla-psa/<product-slug>
        if len(parts) < 2 or parts[0] != "dla-psa":
            return
        slug = parts[-1]
        # Category leaves look like "szelki-dla-psa"; product slugs are longer.
        if slug in {
            "szelki-dla-psa",
            "smycz-dla-psa",
            "obroza-dla-psa",
            "szelki-truelove-front-line",
            "szelki-truelove-front-line-premium",
            "szelki-truelove-adventure",
        }:
            return
        if full not in seen:
            seen.add(full)
            urls.append(full)

    for m in re.finditer(r'href="([^"]+)"', html, re.I):
        _maybe_add(m.group(1))
    return urls


def fetch_html(url: str, *, session: requests.Session | None = None, timeout: int = 30) -> str:
    sess = session or requests.Session()
    headers = {"User-Agent": DEFAULT_USER_AGENT, "Accept-Language": "pl-PL,pl;q=0.9"}
    resp = sess.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"
    return resp.text


def search_truelove_urls(
    *,
    session: requests.Session | None = None,
    max_pages: int = 10,
    query: str = "Truelove",
    category_urls: Iterable[str] | None = None,
) -> list[str]:
    """Collect TipTop Truelove product URLs from category pages (and optional search)."""
    sess = session or requests.Session()
    found: list[str] = []
    seen: set[str] = set()

    sources = list(category_urls or TIPTOP_CATEGORY_URLS)
    # Optional search fallback (often SSR-empty on TipTop)
    sources.append(f"{TIPTOP_SEARCH_URL}?search={query}")

    for base in sources:
        for page in range(1, max_pages + 1):
            if page == 1:
                url = base
            else:
                sep = "&" if "?" in base else "?"
                url = f"{base}{sep}counter={page}"
            try:
                html = fetch_html(url, session=sess)
            except Exception as exc:
                logger.warning("TipTop listing %s failed: %s", url, exc)
                break
            page_urls = extract_product_links_from_listing(html)
            new = [u for u in page_urls if u not in seen]
            if not new and page > 1:
                break
            for u in new:
                seen.add(u)
                found.append(u)
            # Category first page usually has all visible cards; stop if no pager signal
            if "counter=" not in html.lower() and page == 1 and "truelove" in html.lower():
                # still try page 2 once for paginated categories
                continue
    return found


def score_variant_match(
    *,
    tip_name: str,
    tip_size: str | None,
    tip_color: str | None,
    product: Product,
    size: ProductSize,
) -> float | None:
    """Score TipTop variant vs warehouse ProductSize; None = no match."""
    mag_name = product.name or ""
    mag_series = (product.series or "").lower() or _extract_model_series(mag_name)
    tip_series = _extract_model_series(tip_name)
    tip_cat = _extract_category(tip_name)
    mag_cat = (product.category or "") or _extract_category(mag_name)

    if tip_cat and mag_cat and tip_cat != mag_cat:
        return None
    if tip_series and mag_series and tip_series != mag_series.lower():
        # allow partial containment
        if tip_series not in mag_series and mag_series not in tip_series:
            return None
    if tip_size and not _sizes_match(tip_size, size.size or ""):
        return None
    if tip_color and product.color and not _colors_match(tip_color, product.color):
        return None

    tip_words = _normalize_name(tip_name)
    mag_words = _normalize_name(mag_name)
    if not tip_words or not mag_words:
        return None
    common = tip_words & mag_words
    if not common:
        return None
    score = len(common) / len(tip_words | mag_words)
    if tip_series and mag_series and tip_series == mag_series.lower():
        score += 0.4
    if tip_size and _sizes_match(tip_size, size.size or ""):
        score += 0.3
    if tip_color and product.color and _colors_match(tip_color, product.color):
        score += 0.2
    if "truelove" in tip_words:
        score += 0.05
    return score if score >= 0.45 else None


def upsert_parsed_product(db: Session, parsed: ParsedProductPage) -> TipTopProduct:
    product = (
        db.query(TipTopProduct)
        .filter(TipTopProduct.tiptop_product_id == parsed.tiptop_product_id)
        .one_or_none()
    )
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if product is None:
        product = TipTopProduct(
            tiptop_product_id=parsed.tiptop_product_id,
            url=parsed.url,
            name=parsed.name,
            producer=parsed.producer,
            scraped_at=now,
        )
        db.add(product)
    else:
        product.url = parsed.url
        product.name = parsed.name
        product.producer = parsed.producer
        product.scraped_at = now

    existing = {
        (v.size_label or "", v.color_label or ""): v
        for v in db.query(TipTopVariant)
        .filter(TipTopVariant.tiptop_product_id == parsed.tiptop_product_id)
        .all()
    }
    seen_keys: set[tuple[str, str]] = set()
    for row in expand_variants(parsed):
        key = (row["size_label"] or "", row["color_label"] or "")
        seen_keys.add(key)
        variant = existing.get(key)
        option_json = json.dumps(row["option_map"], sort_keys=True)
        if variant is None:
            variant = TipTopVariant(
                tiptop_product_id=parsed.tiptop_product_id,
                option_map=option_json,
                size_label=row["size_label"],
                color_label=row["color_label"],
                available=bool(row["available"]),
                price=row["price"],
            )
            db.add(variant)
        else:
            variant.option_map = option_json
            variant.available = bool(row["available"])
            variant.price = row["price"]

    # Soft-disable variants that disappeared
    for key, variant in existing.items():
        if key not in seen_keys:
            variant.available = False

    db.flush()
    return product


def auto_link_variants(db: Session, *, only_tiptop_product_id: int | None = None) -> tuple[int, int]:
    """Match TipTop variants to ProductSize rows. Returns (created, updated)."""
    q = db.query(TipTopVariant).join(TipTopProduct)
    if only_tiptop_product_id is not None:
        q = q.filter(TipTopVariant.tiptop_product_id == only_tiptop_product_id)
    variants = q.all()
    products = db.query(Product).all()
    sizes_by_product: dict[int, list[ProductSize]] = {}
    for ps in db.query(ProductSize).all():
        sizes_by_product.setdefault(ps.product_id, []).append(ps)

    created = updated = 0
    for variant in variants:
        tip_product = (
            db.query(TipTopProduct)
            .filter(TipTopProduct.tiptop_product_id == variant.tiptop_product_id)
            .one()
        )
        best: tuple[float, ProductSize] | None = None
        for product in products:
            for size in sizes_by_product.get(product.id, []):
                score = score_variant_match(
                    tip_name=tip_product.name,
                    tip_size=variant.size_label,
                    tip_color=variant.color_label,
                    product=product,
                    size=size,
                )
                if score is None:
                    continue
                if best is None or score > best[0]:
                    best = (score, size)
        if best is None:
            continue
        score, size = best
        existing_link = (
            db.query(TipTopProductLink)
            .filter(TipTopProductLink.product_size_id == size.id)
            .one_or_none()
        )
        if existing_link and existing_link.match_type == "manual":
            continue
        if existing_link is None:
            db.add(
                TipTopProductLink(
                    product_size_id=size.id,
                    tiptop_variant_id=variant.id,
                    match_confidence=score,
                    match_type="auto",
                )
            )
            created += 1
        elif existing_link.tiptop_variant_id != variant.id or (
            existing_link.match_confidence or 0
        ) < score:
            existing_link.tiptop_variant_id = variant.id
            existing_link.match_confidence = score
            existing_link.match_type = "auto"
            updated += 1
    db.flush()
    return created, updated


def sync_catalog_from_urls(
    db: Session,
    urls: Iterable[str],
    *,
    http_session: requests.Session | None = None,
    auto_link: bool = True,
) -> CatalogSyncResult:
    """Fetch and upsert TipTop product pages, optionally auto-link to warehouse."""
    result = CatalogSyncResult()
    sess = http_session or requests.Session()
    for url in urls:
        try:
            html = fetch_html(url, session=sess)
            parsed = parse_product_page(html, url)
            # Skip non-Truelove unless producer missing (search already filtered)
            if parsed.producer and "truelove" not in parsed.producer.lower():
                if "truelove" not in parsed.name.lower():
                    continue
            upsert_parsed_product(db, parsed)
            result.products_upserted += 1
            result.variants_upserted += len(expand_variants(parsed))
            if auto_link:
                c, u = auto_link_variants(
                    db, only_tiptop_product_id=parsed.tiptop_product_id
                )
                result.links_created += c
                result.links_updated += u
        except Exception as exc:
            logger.exception("TipTop sync failed for %s", url)
            result.errors.append(f"{url}: {exc}")
    return result


def refresh_truelove_catalog(
    db: Session,
    *,
    max_pages: int = 8,
    max_products: int | None = 200,
) -> CatalogSyncResult:
    """Search TipTop for Truelove and sync product pages into cache."""
    urls = search_truelove_urls(max_pages=max_pages)
    if max_products is not None:
        urls = urls[:max_products]
    return sync_catalog_from_urls(db, urls)


def cart_item_from_link(link: TipTopProductLink, quantity: int) -> dict[str, Any]:
    """Build Front API basket payload item from a TipTopProductLink."""
    variant = link.variant
    product = variant.product
    option_map = json.loads(variant.option_map or "{}")
    # Front API expects int values
    options = {str(k): int(v) for k, v in option_map.items()}
    return {
        "stock_id": product.tiptop_product_id,
        "quantity": int(quantity),
        "options": options,
        "label": f"{product.name} / {variant.size_label or '-'} / {variant.color_label or '-'}",
        "product_size_id": link.product_size_id,
        "tiptop_url": product.url,
    }


__all__ = [
    "BASKET_API_PATH",
    "CatalogSyncResult",
    "ParsedProductPage",
    "TIPTOP_BASE",
    "auto_link_variants",
    "cart_item_from_link",
    "expand_variants",
    "extract_product_links_from_listing",
    "fetch_html",
    "parse_product_page",
    "refresh_truelove_catalog",
    "score_variant_match",
    "search_truelove_urls",
    "sync_catalog_from_urls",
]
