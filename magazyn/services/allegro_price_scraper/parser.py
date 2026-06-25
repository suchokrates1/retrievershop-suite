"""Parser tekstowych kafelkow ofert Allegro."""

from __future__ import annotations

import logging
import re
import urllib.parse
from typing import Any

from .config import MY_SELLER, COMPETITOR_PRICES_ARE_NET, STANDARD_VAT_RATE
from .delivery import parse_delivery_days
from .models import CompetitorOffer

logger = logging.getLogger(__name__)


def parse_price(price_str: str) -> float:
    """Parsuje cene Allegro do float."""
    if price_str is None:
        raise ValueError("Brak ceny")

    normalized = str(price_str).strip()
    normalized = re.sub(r"(?i)\b(?:zł|zl|pln)\b", "", normalized)
    normalized = re.sub(r"[\s\u00a0\u202f]", "", normalized)
    normalized = re.sub(r"[^0-9,.\-]", "", normalized)
    if not normalized:
        raise ValueError(f"Nieprawidlowa cena: {price_str!r}")

    if "," in normalized:
        normalized = normalized.replace(".", "").replace(",", ".")
    return float(normalized)


def is_net_price_label(text: str | None) -> bool:
    """True gdy etykieta lub fragment tekstu wskazuje cene netto (nie brutto)."""
    if not text:
        return False

    normalized = text.lower().translate(str.maketrans("ąćęłńóśźż", "acelnoszz"))
    if "brutto" in normalized:
        return False
    return bool(re.search(r"\bnetto\b", normalized))


def is_net_price_article(text: str, aria_label: str | None = None) -> bool:
    """Wykrywa czy kafelek oferty pokazuje cene netto (konto firmowe Allegro)."""
    if is_net_price_label(aria_label):
        return True

    if not text:
        return False

    normalized = text.lower().translate(str.maketrans("ąćęłńóśźż", "acelnoszz"))
    if "brutto" in normalized:
        return False

    for line in normalized.splitlines():
        if "netto" not in line:
            continue
        if re.search(r"\d+(?:[.,]\d{2})?\s*zl", line):
            return True

    lines = normalized.splitlines()
    for index, line in enumerate(lines):
        if "netto" not in line:
            continue
        window = "\n".join(lines[max(0, index - 1) : index + 2])
        if re.search(r"\d+(?:[.,]\d{2})?\s*zl", window):
            return True

    return bool(
        re.search(r"\d+(?:[.,]\d{2})?\s*zl[^\n]{0,40}\bnetto\b", normalized)
        or re.search(r"\bnetto\b[^\n]{0,40}\d+(?:[.,]\d{2})?\s*zl", normalized)
    )


def gross_from_net(net_price: float, vat_rate: float = STANDARD_VAT_RATE) -> float:
    """Konwertuje cene netto na brutto (zaokraglenie do groszy)."""
    return round(net_price * (1.0 + vat_rate), 2)


_VAT_GROSS_RE = re.compile(
    r"([\d\s\u00a0\u202f]+,\d{2})\s*z[łl]\s*z\s*\d{1,2}\s*%\s*VAT", re.IGNORECASE
)
_VAT_DELIVERY_GROSS_RE = re.compile(
    r"([\d\s\u00a0\u202f]+,\d{2})\s*z[łl]\s*z\s*dostaw[aąy][^\n]*?z\s*VAT", re.IGNORECASE
)
_NO_VAT_RE = re.compile(r"\bbez\s+VAT\b", re.IGNORECASE)


def _first_price(pattern: re.Pattern[str], text: str) -> float | None:
    match = pattern.search(text or "")
    if not match:
        return None
    try:
        return parse_price(match.group(1))
    except (TypeError, ValueError):
        return None


def resolve_gross_prices(
    text: str,
    net_price: float,
    net_total: float,
    assume_net: bool,
) -> tuple[float, float, str]:
    """Ustala brutto na podstawie jawnego VAT z tekstu kafelka.

    Allegro na koncie firmowym pokazuje obok ceny netto dokladne brutto:
    ``231,00 zl z 23% VAT`` (jawny VAT) albo ``219,99 zl bez VAT`` (sprzedawca
    zwolniony -> brutto == netto). Korzystamy z tego zamiast slepego x1.23.

    Zwraca (brutto, brutto_z_dostawa, zrodlo).
    """
    explicit = _first_price(_VAT_GROSS_RE, text)
    if explicit is not None:
        gross, source = explicit, "vat_line"
    elif _NO_VAT_RE.search(text or ""):
        gross, source = net_price, "bez_vat"
    elif assume_net:
        gross, source = gross_from_net(net_price), "assumed_net"
    else:
        gross, source = net_price, "as_is"

    ratio = (gross / net_price) if net_price else 1.0
    explicit_delivery = _first_price(_VAT_DELIVERY_GROSS_RE, text)
    if explicit_delivery is not None:
        gross_total = explicit_delivery
    else:
        gross_total = round(net_total * ratio, 2)
    return gross, gross_total, source


def normalize_seller_name(seller_name: str) -> str:
    """Normalizuje login sprzedawcy do porownan i filtrowania."""
    return str(seller_name or "").strip().casefold()


def build_offer_url(offer_id: str, title: str = "") -> str:
    """Buduje URL oferty z fragmentem #inne-oferty-produktu."""
    if title:
        transliteration = str.maketrans("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ", "acelnoszzACELNOSZZ")
        slug = title.lower().translate(transliteration)
        slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
        return f"https://allegro.pl/oferta/{slug}-{offer_id}#inne-oferty-produktu"
    return f"https://allegro.pl/oferta/x-{offer_id}#inne-oferty-produktu"


def detect_offer_condition(text: str) -> str:
    """Normalizuje stan oferty z tekstu kafelka Allegro."""
    if not text:
        return ""

    normalized = text.lower().translate(str.maketrans("ąćęłńóśźż", "acelnoszz"))
    patterns = (
        (r"\bpowy?stawow\w*\b", "powystawowy"),
        (r"\buzywan\w*\b", "uzywany"),
        (r"\bodnowiony\s+przez\s+sprzedawc\w*\b", "odnowiony"),
        (r"\bnowy\b", "nowy"),
    )
    for pattern, label in patterns:
        if re.search(pattern, normalized):
            return label
    return ""


def is_excluded_offer_condition(condition: str) -> bool:
    """Zwraca True dla stanow ofert, ktorych nie chcemy uwzgledniac w rankingu."""
    return condition in {"powystawowy", "uzywany", "odnowiony"}


def parse_competitor_articles(
    articles: list[dict[str, Any]],
    product_title: str = "",
    dialog_shows_net_prices: bool = False,
    competitor_prices_are_net: bool | None = None,
) -> list[CompetitorOffer]:
    """Parsuje surowe artykuly z dialogu na oferty konkurencji."""
    if not articles:
        return []

    if competitor_prices_are_net is None:
        competitor_prices_are_net = COMPETITOR_PRICES_ARE_NET

    offers = []
    for article in articles:
        text = article.get("text", "")
        offer_id = article.get("offerId")
        js_offer_url = article.get("offerUrl")

        if not text or len(text) < 15 or "zł" not in text:
            logger.debug("Pominiety article %s: brak ceny lub za krotki", article.get("index"))
            continue

        review_keywords = ("NAJBARDZIEJ POMOCNA", "Treść recenzji", "Tresc recenzji")
        if any(keyword in text for keyword in review_keywords):
            logger.debug("Pominiety article %s: recenzja produktu", article.get("index"))
            continue

        seller_match = re.search(r"\|\s*\n\s*(\S+)", text)
        if not seller_match:
            seller_match = re.search(r"\bod\s*\n(?:Super Sprzedawcy\s*\n)?\s*(\S+)", text)

        aria_price = article.get("ariaPrice")
        aria_price_label = article.get("ariaPriceLabel")
        delivery_match = re.search(r"(\d+(?:,\d{2})?)\s*zł\s*z\s*dostaw", text)
        delivery_price_str = delivery_match.group(1) if delivery_match else None

        if aria_price:
            price_match_value = aria_price
        else:
            clean_text = re.sub(r"(?:Kupon|Cashback|Rabat)\s+\d+(?:,\d{2})?\s*zł", "", text)
            all_prices = re.findall(r"(\d+(?:,\d{2})?)\s*zł\s*\n", clean_text)
            price_match_value = all_prices[-1] if all_prices else None

        delivery_months = r"(?:sty|lut|mar|kwi|maj|cze|lip|sie|wrz|pa[zź]|lis|gru)"
        delivery_text_pattern = (
            r"(dostawa\s+(?:"
            rf"(?:pon|wt|[sś]r|czw|pt|sob|niedz)\.?\s+\d{{1,2}}\s+{delivery_months}\.?"
            r"|w\s+\w+"
            r"|za\s+\d+.*?dni"
            r"|od\s+\d+"
            rf"|\d{{1,2}}\s+{delivery_months}\.?"
            r"|pojutrze|jutro|dzisiaj|dzi[sś]"
            r"))"
        )
        delivery_text_match = re.search(delivery_text_pattern, text, re.IGNORECASE)

        seller = seller_match.group(1) if seller_match else "nieznany"
        condition = detect_offer_condition(text)
        if not price_match_value:
            continue

        try:
            price = parse_price(price_match_value)
            total = parse_price(delivery_price_str) if delivery_price_str else price
        except (TypeError, ValueError) as exc:
            logger.warning(
                "Pominiety article %s: nieprawidlowa cena (%r / %r): %s",
                article.get("index"),
                price_match_value,
                delivery_price_str,
                exc,
            )
            continue

        assume_net = (
            competitor_prices_are_net
            or dialog_shows_net_prices
            or is_net_price_article(text, aria_price_label)
        )
        if assume_net and "brutto" in (aria_price_label or "").lower():
            assume_net = False

        net_price = price
        price, total, gross_source = resolve_gross_prices(text, price, total, assume_net)
        if gross_source != "as_is" and price != net_price:
            logger.debug(
                "Article %s: cena netto %s -> brutto %s (zrodlo=%s)",
                article.get("index"),
                net_price,
                price,
                gross_source,
            )

        if price < 1.0:
            logger.warning(
                "Pominiety article %s: cena %s zl < 1 zl (prawdopodobny blad parsowania)",
                article.get("index"),
                price,
            )
            continue

        delivery_text = delivery_text_match.group(1) if delivery_text_match else ""
        offer_url = ""
        if js_offer_url:
            offer_url = js_offer_url
        elif offer_id:
            offer_url = f"https://allegro.pl/oferta/x-{offer_id}"
        elif seller and seller != "nieznany" and product_title:
            search_query = urllib.parse.quote(product_title[:50])
            offer_url = f"https://allegro.pl/listing?string={search_query}&sellerLogin={seller}"

        offers.append(
            CompetitorOffer(
                seller=seller,
                price=price,
                price_with_delivery=total,
                is_mine=normalize_seller_name(seller) == normalize_seller_name(MY_SELLER),
                delivery_days=parse_delivery_days(delivery_text),
                delivery_text=delivery_text,
                offer_url=offer_url,
                is_super_seller=bool(re.search(r"Super\s+Sprzedawc", text)),
                has_smart=bool(re.search(r"Smart!|smart!", text)),
                offer_id=offer_id,
                condition=condition,
            )
        )

    return deduplicate_offers(offers)


def deduplicate_offers(offers: list[CompetitorOffer]) -> list[CompetitorOffer]:
    """Usuwa duplikaty ofert po offer_id albo parze sprzedawca/cena."""
    seen = set()
    unique_offers = []
    for offer in offers:
        key = offer.offer_id if offer.offer_id else f"{offer.seller}_{offer.price:.2f}"
        if key in seen:
            logger.debug("Duplikat oferty: %s (seller=%s, price=%s)", key, offer.seller, offer.price)
            continue
        seen.add(key)
        unique_offers.append(offer)

    if len(unique_offers) < len(offers):
        logger.info("Usunieto %s duplikatow ofert", len(offers) - len(unique_offers))

    return unique_offers


def filter_competitor_offers(
    offers: list[CompetitorOffer],
    excluded_sellers: set,
    max_delivery_days: int,
) -> tuple[list[CompetitorOffer], dict[str, int]]:
    """Filtruje konkurencje po dostawie, liscie wykluczen i stanie oferty."""
    stats = {"delivery": 0, "excluded_sellers": 0, "condition": 0}
    normalized_excluded_sellers = {
        normalized
        for seller in excluded_sellers
        if (normalized := normalize_seller_name(seller))
    }
    filtered = []

    for offer in offers:
        if offer.delivery_days is not None and offer.delivery_days >= max_delivery_days:
            stats["delivery"] += 1
            continue
        if normalize_seller_name(offer.seller) in normalized_excluded_sellers:
            stats["excluded_sellers"] += 1
            continue
        if is_excluded_offer_condition(offer.condition):
            stats["condition"] += 1
            continue
        filtered.append(offer)

    return filtered, stats