from __future__ import annotations

import re
import unicodedata

from .constants import (
    ALL_SIZES,
    KNOWN_COLORS,
    normalize_product_title_fragment,
    resolve_product_alias,
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
}

# Mapping of normalized product keywords to canonical product names.  The
# priority value controls which keyword should win when multiple keywords are
# present in the offer title.
PRODUCT_KEYWORDS: list[tuple[str, str, int]] = [
    ("tropical", "Szelki dla psa Truelove Tropical", 2),
    ("adventure dog", "Szelki dla psa Truelove Adventure Dog", 2),
    ("safe hiking", "Szelki dla psa Truelove Safe Hiking", 2),
    ("lumen", "Szelki dla psa Truelove Lumen", 1),
    ("blossom", "Szelki dla psa Truelove Blossom", 2),
    ("front line premium", "Szelki dla psa Truelove Front Line Premium", 1),
    ("front line", "Szelki dla psa Truelove Front Line", 0),
]


def _strip_diacritics(value: str) -> str:
    """Return *value* lower-cased and stripped of diacritics."""

    normalized = unicodedata.normalize("NFKD", value.lower())
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


def _detect_product_keyword(title: str) -> str:
    """Return canonical product name if *title* contains a known keyword."""

    normalized_title = _normalize_keyword_text(title)
    if not normalized_title:
        return ""

    padded_title = f" {normalized_title} "
    matches: list[tuple[int, int, str]] = []
    for keyword, canonical, priority in PRODUCT_KEYWORDS:
        normalized_keyword = _normalize_keyword_text(keyword)
        if not normalized_keyword:
            continue
        if f" {normalized_keyword} " in padded_title:
            matches.append((priority, len(normalized_keyword), canonical))

    if not matches:
        return ""

    priority, _, canonical = max(matches, key=lambda item: (item[0], item[1]))
    return resolve_product_alias(normalize_product_title_fragment(canonical))


def parse_product_info(item: dict) -> tuple[str, str, str]:
    """Return product name, size and color from an order item."""
    if not item:
        return "", "", ""

    name = item.get("name", "") or ""

    # Usun szum z nazwy: znaczniki dlugosci (2m, 1.5m) i slowo "material"
    name = re.sub(r'\b\d+(?:[.,]\d+)?m\b', '', name).strip()
    name = re.sub(r'\bmateria[\u0142l]\b', '', name, flags=re.IGNORECASE).strip()
    name = re.sub(r'\s+', ' ', name)

    size = ""
    color = ""

    for attr in item.get("attributes", []):
        aname = (attr.get("name") or "").lower()
        if aname in {"rozmiar", "size"} and not size:
            size = attr.get("value", "")
        elif aname in {"kolor", "color"} and not color:
            color = attr.get("value", "")

    if not size:
        words = name.strip().split()
        known_colors_norm = {_strip_diacritics(c.lower()) for c in KNOWN_COLORS}
        if len(words) >= 3:
            maybe_size = words[-1]
            if maybe_size.upper() in {s.upper() for s in ALL_SIZES}:
                size = maybe_size
                if not color:
                    candidate_color = words[-2]
                    if _strip_diacritics(candidate_color.lower()) in known_colors_norm:
                        color = candidate_color
                        name = " ".join(words[:-2])
                    else:
                        # Nie jest znanym kolorem - zostaw w nazwie
                        name = " ".join(words[:-1])
                else:
                    name = " ".join(words[:-1])
        if not size and len(words) >= 2:
            maybe_color = words[-1].lower()
            if maybe_color in {c.lower() for c in KNOWN_COLORS}:
                if len(words) >= 3 and words[-2].upper() in {s.upper() for s in ALL_SIZES}:
                    size = words[-2]
                    if not color:
                        color = words[-1]
                    name = " ".join(words[:-2])
                else:
                    if not color:
                        color = words[-1]
                    size = "Uniwersalny"
                    name = " ".join(words[:-1])

    name = normalize_product_title_fragment(name.strip())
    name = resolve_product_alias(name)
    color = normalize_color(color)
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

    name = _detect_product_keyword(title)
    if not name:
        name = " ".join(remaining_words).strip()
        name = normalize_product_title_fragment(name)
        name = resolve_product_alias(name)

    if not size:
        size = "Uniwersalny"

    return name, color, size
