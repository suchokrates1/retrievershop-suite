from __future__ import annotations

import re
import unicodedata

from .constants import (
    ALL_SIZES,
    KNOWN_COLORS,
    normalize_product_title_fragment,
    resolve_product_alias,
)

# Kanoniczne nazwy produktow bez wariantow rozmiarowych (jeden SKU / kolor).
_SINGLE_SIZE_NAME_PREFIXES = (
    "Amortyzator dla psa",
    "Pas samochodowy dla psa",
    "Pas trekkingowy dla psa",
)

COLOR_ALIASES = {
    "czerwone": "czerwony",
    "czerwona": "czerwony",
    "niebieskie": "niebieski",
    "niebieska": "niebieski",
    "zielone": "zielony",
    "zielona": "zielony",
    "czarne": "czarny",
    "czarna": "czarny",
    "białe": "biały",
    "biała": "biały",
    "brązowe": "brązowy",
    "brązowa": "brązowy",
    "różowe": "różowy",
    "różowa": "różowy",
    "róż": "różowy",
    "różow": "różowy",
    "fioletowe": "fioletowy",
    "fioletowa": "fioletowy",
    "srebrne": "srebrny",
    "srebrna": "srebrny",
    "pomarańczowe": "pomarańczowy",
    "pomarańczowa": "pomarańczowy",
    "turkusowe": "turkusowy",
    "turkusowa": "turkusowy",
    "granatowe": "granatowy",
    "granatowa": "granatowy",
    "szare": "szary",
    "szara": "szary",
    "żółte": "żółty",
    "żółta": "żółty",
    "limonkowe": "limonkowy",
    "limonkowa": "limonkowy",
    "khaki": "zielony",
    "zielony-khaki": "zielony",
    "zielony khaki": "zielony",
    "fiolet": "fioletowy",
    "stalowa roz": "stalowy rozowy",
    "stalowa roza": "stalowy rozowy",
    "stalowa rozowa": "stalowy rozowy",
}

# Slowa kluczowe kategorii produktu w tytule oferty.
# (keyword, prefiks_kategorii, domyslna_seria, priorytet)
# Priorytet rozwiazuje konflikty gdy kilka kategorii pasuje (np. "amortyzator do smyczy").
CATEGORY_KEYWORDS: list[tuple[str, str, str | None, int]] = [
    ("pas samochodowy", "Pas samochodowy dla psa", "Premium", 3),
    ("pas trekkingowy", "Pas trekkingowy dla psa", "Trek Go", 3),
    ("pas do biegania", "Pas trekkingowy dla psa", "Trek Go", 3),
    ("dogtrekking", "Pas trekkingowy dla psa", "Trek Go", 3),
    ("amortyzator do smyczy", "Amortyzator dla psa", "Premium", 3),
    ("amortyaator do smyczy", "Amortyzator dla psa", "Premium", 3),
    ("amortyzator", "Amortyzator dla psa", "Premium", 2),
    ("kamizelka ratunkowa", "Kapok dla psa", "Dive", 5),
    ("kamizelka", "Kamizelka dla psa", "Chłodząca", 3),
    ("kapok", "Kapok dla psa", None, 4),
    ("saszetki", "Saszetki dla psa", None, 2),
    ("saszetka", "Saszetki dla psa", None, 2),
    ("torebka", "Saszetki dla psa", None, 2),
    ("przysmaki", "Saszetki dla psa", None, 1),
    ("smycz automatyczna", "Smycz dla psa", "Handy", 2),
    ("obroza", "Obroża dla psa", None, 1),
    ("smycz", "Smycz dla psa", None, 1),
    ("szelki", "Szelki dla psa", None, 0),
]

# Slowa kluczowe serii produktu w tytule oferty.
# (keyword, nazwa_serii, priorytet)
# Priorytet rozwiazuje konflikty (np. "front line" vs "front line premium").
SERIES_KEYWORDS: list[tuple[str, str, int]] = [
    # Aliasy: "Front Line (Premium) + seria" -> ta seria wygrywa
    ("front line premium tropical", "Tropical", 5),
    ("front line tropical", "Tropical", 4),
    ("front line premium lumen", "Lumen", 5),
    ("front line lumen", "Lumen", 4),
    ("front line premium blossom", "Blossom", 5),
    ("front line blossom", "Blossom", 4),
    # Cordura - osobna seria
    ("front line premium cordura", "Front Line Premium Cordura", 5),
    ("front line cordura", "Front Line Premium Cordura", 4),
    # Front Line
    ("front line premium", "Front Line Premium", 2),
    ("front line", "Front Line", 1),
    # Pozostale serie
    ("adventure soft", "Adventure Soft", 3),
    ("adventure dog", "Adventure Dog", 2),
    ("adventure", "Adventure", 1),
    ("safe hiking", "Safe Hiking", 2),
    ("lumen lite", "Lumen Lite", 2),
    ("lumen", "Lumen", 1),
    ("blossom", "Blossom", 2),
    ("tropical", "Tropical", 2),
    ("dive", "Dive", 3),
    ("active", "Active", 1),
    ("chlodzaca", "Chłodząca", 3),
    ("tradycyjna", "Active", 3),
    ("active pro+", "Active Pro+", 4),
    ("active pro", "Active Pro+", 3),
    ("na przysmaki", "Standard", 2),
    ("torebka na przysmaki", "Treat Basic", 3),
    ("trening sportowy", "Treat Basic", 2),
    ("outdoor", "Outdoor", 2),
    ("security", "Security", 2),
    ("tracker", "Tracker", 2),
    ("handy", "Handy", 2),
    ("automatyczna", "Handy", 1),
    ("dogi", "Dogi", 2),
    ("trek go", "Trek Go", 2),
    ("premium", "Premium", 0),
    ("trail bag", "Trail Bag", 2),
    ("standard", "Standard", 2),
    ("treat basic", "Treat Basic", 3),
    ("v2", "V2", 2),
    ("v1", "V1", 2),
]


def _strip_diacritics(value: str) -> str:
    """Return *value* lower-cased and stripped of diacritics."""

    lowered = value.lower().replace("ł", "l")
    normalized = unicodedata.normalize("NFKD", lowered)
    return "".join(char for char in normalized if not unicodedata.combining(char))


def normalize_color(color: str) -> str:
    if not color:
        return ""
    normalized_color = _strip_diacritics(color).lower()
    
    # Try exact match first
    for alias, canonical in COLOR_ALIASES.items():
        normalized_alias = _strip_diacritics(alias).lower()
        if normalized_color == normalized_alias:
            return canonical.capitalize()
    
    # Try prefix match for compound colors
    base_match = ""
    base_color = color.lower()
    for alias, canonical in COLOR_ALIASES.items():
        normalized_alias = _strip_diacritics(alias).lower()
        if normalized_color.startswith(normalized_alias):
            if len(normalized_alias) > len(base_match):
                base_match = normalized_alias
                base_color = canonical
    return base_color.capitalize()



def _normalize_keyword_text(value: str) -> str:
    """Return normalized representation for keyword matching."""

    normalized = _strip_diacritics(value)
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _is_single_size_product(detected_name: str) -> bool:
    """Czy wykryta nazwa produktu oznacza jeden rozmiar (Uniwersalny).

    Decyzja opiera sie na kategorii z ``_detect_product_name``, a nie na
    substringach w surowym tytule - np. smycz *z amortyzatorem* ma M/L.
    """
    if not detected_name:
        return False
    if detected_name.startswith(_SINGLE_SIZE_NAME_PREFIXES):
        return True
    # Smycz automatyczna (Handy) - jeden SKU na kolor.
    return (
        detected_name.startswith("Smycz dla psa")
        and " Handy" in detected_name
    )


def _detect_product_name(title: str) -> str:
    """Rozpoznaj nazwe produktu z tytulu oferty: kategoria + seria.

    Buduje kanonyczna nazwe produktu w formacie:
    ``{kategoria} Truelove {seria}`` (np. "Obroza dla psa Truelove Lumen").
    """

    # Krok 0: Normalizacja literowek (Fron->Front, FrontLine->Front Line)
    cleaned_title = normalize_product_title_fragment(title)
    normalized_title = _normalize_keyword_text(cleaned_title)
    if not normalized_title:
        return ""

    padded_title = f" {normalized_title} "

    # Krok 1: Wykryj kategorie (szelki, obroza, smycz, ...)
    category_prefix = ""
    implied_series = None
    cat_matches: list[tuple[int, int, str, str | None]] = []
    for keyword, prefix, default_series, priority in CATEGORY_KEYWORDS:
        nk = _normalize_keyword_text(keyword)
        if not nk:
            continue
        if f" {nk} " in padded_title:
            cat_matches.append((priority, len(nk), prefix, default_series))

    if cat_matches:
        _, _, category_prefix, implied_series = max(
            cat_matches, key=lambda x: (x[0], x[1])
        )

    if not category_prefix:
        return ""

    # Krok 2: Wykryj serie (Front Line Premium, Lumen, Active, ...)
    series_name = ""
    series_matches: list[tuple[int, int, str]] = []
    for keyword, series, priority in SERIES_KEYWORDS:
        nk = _normalize_keyword_text(keyword)
        if not nk:
            continue
        if f" {nk} " in padded_title:
            series_matches.append((priority, len(nk), series))

    if series_matches:
        _, _, series_name = max(series_matches, key=lambda x: (x[0], x[1]))
    elif implied_series:
        series_name = implied_series

    # Krok 3: Zbuduj kanonyczna nazwe produktu
    if series_name:
        return f"{category_prefix} Truelove {series_name}"
    return f"{category_prefix} Truelove"


def parse_product_info(item: dict) -> tuple[str, str, str]:
    """Return product name, size and color from an order item."""
    if not item:
        return "", "", ""

    raw_name = item.get("name", "") or ""

    attr_size = ""
    attr_color = ""
    for attr in item.get("attributes", []):
        aname = (attr.get("name") or "").lower()
        if aname in {"rozmiar", "size"} and not attr_size:
            attr_size = attr.get("value", "")
        elif aname in {"kolor", "color"} and not attr_color:
            attr_color = attr.get("value", "")

    offer_name, offer_color, offer_size = parse_offer_title(raw_name)

    detected_name = _detect_product_name(raw_name)
    if detected_name:
        name = resolve_product_alias(detected_name)
    else:
        name = offer_name

    size = attr_size or offer_size
    color = normalize_color(attr_color or offer_color)

    return name, size, color


def parse_offer_title(title: str) -> tuple[str, str, str]:
    """Split an Allegro offer title into product name, color and size.

    Parameters
    ----------
    title:
        Raw title string fetched from Allegro.

    Returns
    -------
    tuple[str, str, str]
        ``(name, color, size)`` tuple where size defaults to ``"Uniwersalny"``
        when it could not be inferred from the title.
    """

    if not title:
        return "", "", "Uniwersalny"

    # Usun oznaczenia długości smyczy (np. "5 metrów") - nie są rozmiarem
    title = re.sub(r'\b\d+(?:[.,]\d+)?\s*metr\w*\b', '', title, flags=re.IGNORECASE).strip()

    words = [word for word in (title or "").strip().split() if word]
    size_lookup = {size.upper(): size for size in ALL_SIZES}
    normalized_known_colors = [
        (_strip_diacritics(color), color) for color in KNOWN_COLORS
    ]

    color = ""
    size = ""

    cleaned_words: list[str] = []
    for word in words:
        cleaned_words.append(word.strip(",.;:!"))

    # Work on a copy so we can safely remove identified size/color tokens.
    remaining_words = cleaned_words.copy()

    for index in range(len(cleaned_words) - 1, -1, -1):
        word = cleaned_words[index]
        upper_word = word.upper()
        if not size and upper_word in size_lookup:
            size = size_lookup[upper_word]
            remaining_words.pop(index)
            continue
        lower_word = word.lower()
        if not color:
            normalized_word = _strip_diacritics(lower_word)
            matched_color = ""
            matched_length = 0
            for normalized_color, original_color in normalized_known_colors:
                if normalized_word.startswith(normalized_color) and len(normalized_color) > matched_length:
                    matched_color = original_color
                    matched_length = len(normalized_color)
            if matched_color:
                color = normalize_color(matched_color)
                remaining_words.pop(index)

    detected_name = _detect_product_name(title)
    if detected_name:
        name = resolve_product_alias(detected_name)
    else:
        name = " ".join(remaining_words).strip()
        name = normalize_product_title_fragment(name)
        name = resolve_product_alias(name)

    if not size:
        size = "Uniwersalny"

    if _is_single_size_product(detected_name or name):
        size = "Uniwersalny"

    return name, color, size
