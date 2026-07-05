from __future__ import annotations

import re
import unicodedata

ALL_SIZES = ["XS", "S", "M", "L", "XL", "2XL", "3XL", "Uniwersalny"]

# Product categories
PRODUCT_CATEGORIES = [
    "Szelki",
    "Smycz",
    "Pas bezpieczeństwa",
    "Obroża",
    "Saszetki",
    "Amortyzator",
    "Kapok",
    "Kamizelka",
    "Linka",
]

# Known brands
PRODUCT_BRANDS = [
    "Truelove",
    "Hexa",
    "Julius-K9",
    "Ruffwear",
    "Hurtta",
]

# Product series (mainly Truelove)
PRODUCT_SERIES = [
    "Front Line Premium",
    "Front Line Cordura",
    "Front Line",
    "Active",
    "Active Pro+",
    "Blossom",
    "Tropical",
    "Dive",
    "Chłodząca",
    "Treningowa wodoodporna 13mm 5m",
    "Lumen",
    "Amor",
    "Classic",
    "Neon",
    "Reflective",
    "Adventure",
    "Adventure Soft",
    "Adventure Dog",
    "Safe Hiking",
    "Handy",
    "Dogi",
    "Outdoor",
    "Security",
    "Trail Bag",
    "Standard",
    "V1",
    "V2",
    "Treat Basic",
]

# Common color names that may appear in product titles.  They are stored in
# lowercase form to simplify comparisons when parsing strings.
KNOWN_COLORS = [
    "czerwony",
    "czerwone",
    "czerwona",
    "niebieski",
    "niebieskie",
    "niebieska",
    "zielony",
    "zielone",
    "zielona",
    "czarny",
    "czarne",
    "czarna",
    "biały",
    "białe",
    "biała",
    "brązowy",
    "brązowe",
    "brązowa",
    "różowy",
    "różowe",
    "różow",
    "róż",
    "fioletowy",
    "fioletowe",
    "fioletowa",
    "srebrny",
    "srebrne",
    "srebrna",
    "pomarańczowy",
    "pomarańczowe",
    "pomarańczowa",
    "turkusowy",
    "turkusowe",
    "turkusowa",
    "granatowy",
    "granatowe",
    "granatowa",
    "szary",
    "szare",
    "szara",
    "żółty",
    "żółte",
    "żółta",
    "limonkowy",
    "limonkowe",
    "limonkowa",
    "bananowy",
    "bananowe",
    "bananowa",
    "liliowy",
    "liliowe",
    "liliowa",
    "khaki",
    "zielony-khaki",
    "fiolet",
    "stalowy rozowy",
    "stalowa roz",
]

# Regex rules used to normalize product titles and alias lookups.  The patterns
# are applied in order which allows the more specific replacements (e.g. with
# "Premium") to run before the general ones.
_PRODUCT_TITLE_REPLACEMENTS = [
    # Literowki w nazwie marki
    (re.compile(r"\btruelobve\b", re.IGNORECASE), "Truelove"),
    (re.compile(r"\btuelove\b", re.IGNORECASE), "Truelove"),
    (re.compile(r"\btrelove\b", re.IGNORECASE), "Truelove"),
    # Literowki w "psa" / kategorii
    (re.compile(r"\bpda\b", re.IGNORECASE), "psa"),
    (re.compile(r"\bsrednieho\b", re.IGNORECASE), "średniego"),
    (re.compile(r"\bamortyaator\b", re.IGNORECASE), "Amortyzator"),
    # Literowki w "Front"
    (re.compile(r"\bfron\b", re.IGNORECASE), "Front"),
    (re.compile(r"\bfrone\b", re.IGNORECASE), "Front"),
    (re.compile(r"\bftont\b", re.IGNORECASE), "Front"),
    (
        re.compile(r"\bfront[\s-]*line\s+premium\b", re.IGNORECASE),
        "Front Line Premium",
    ),
    (re.compile(r"\bfront[\s-]*line\b", re.IGNORECASE), "Front Line"),
    # Deskryptory szumowe w tytulach Allegro - usuwane przy matchowaniu
    (re.compile(r"\bmateria[l\u0142]ow[aey]\b", re.IGNORECASE), ""),
    (re.compile(r"\bmateria[l\u0142]\b", re.IGNORECASE), ""),
    (re.compile(r"\bodblaskow[aey]\b", re.IGNORECASE), ""),
    (re.compile(r"\bantyucieczkow[aey]\b", re.IGNORECASE), ""),
    # Znaczniki dlugosci (2m, 1.5m, 250 cm itp.)
    (re.compile(r"\b\d+(?:[.,]\d+)?\s*(?:m|metr\w*|cm)\b", re.IGNORECASE), ""),
    (re.compile(r"\bduza\b", re.IGNORECASE), ""),
]


def _apply_title_replacements(value: str) -> str:
    """Return *value* with known typos corrected and whitespace normalized."""

    result = value or ""
    for pattern, replacement in _PRODUCT_TITLE_REPLACEMENTS:
        result = pattern.sub(replacement, result)
    result = re.sub(r"\s+", " ", result).strip()
    return result


def normalize_product_title_fragment(value: str) -> str:
    """Return title fragment with consistent wording for matching purposes."""

    return _apply_title_replacements(value)


def _normalize_alias_key(value: str) -> str:
    """Return a case-folded key used when looking up product aliases."""

    normalized = unicodedata.normalize("NFKC", value or "").casefold()
    for pattern, replacement in _PRODUCT_TITLE_REPLACEMENTS:
        normalized = pattern.sub(replacement.casefold(), normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


_PRODUCT_ALIAS_GROUPS: dict[str, set[str]] = {
    "Amortyzator dla psa Truelove Premium": {
        "Amortyzator do smyczy dla średniego psa Truelove",
        "Amortyzator do smyczy dla średniego psa",
    },
    "Smycz dla psa Truelove Active": {
        "Smycz tradycyjna Truelove",
        "Smycz tradycyjna dla psa Truelove",
    },
    "Saszetki dla psa Truelove Standard": {
        "Saszetka na przysmaki Truelove",
        "Saszetki na przysmaki Truelove",
        "Duża saszetka na przysmaki dla psa Truelove",
    },
    "Szelki dla psa Truelove Tropical": {
        "Szelki dla psa Truelove Front Line Premium Tropical",
        "Szelki dla psa Truelove FrontLine Premium Tropical",
        "Szelki dla psa Truelove Front-Line Premium Tropical",
        "Szelki dla psa Truelove Fron Line Premium Tropical",
    },
    "Szelki dla psa Truelove Front Line": {
        "Szelki dla psa Truelove FrontLine",
        "Szelki dla psa Truelove Front-Line",
        "Szelki dla psa Truelove Fron Line",
    },
    "Szelki dla psa Truelove Front Line Premium": {
        "Szelki dla psa Truelove FrontLine Premium",
        "Szelki dla psa Truelove Front-Line Premium",
        "Szelki dla psa Truelove Fron Line Premium",
    },
    "Szelki dla psa Truelove Lumen": {
        "Szelki dla psa Truelove Front Line Lumen",
        "Szelki dla psa Truelove Front Line Premium Lumen",
        "Szelki dla psa Truelove FrontLine Lumen",
        "Szelki dla psa Truelove FrontLine Premium Lumen",
        "Szelki dla psa Truelove Front-Line Lumen",
        "Szelki dla psa Truelove Front-Line Premium Lumen",
        "Szelki dla psa Truelove Fron Line Lumen",
        "Szelki dla psa Truelove Fron Line Premium Lumen",
    },
    "Szelki dla psa Truelove Blossom": {
        "Szelki dla psa Truelove Front Line Blossom",
        "Szelki dla psa Truelove Front Line Premium Blossom",
        "Szelki dla psa Truelove FrontLine Blossom",
        "Szelki dla psa Truelove FrontLine Premium Blossom",
        "Szelki dla psa Truelove Front-Line Blossom",
        "Szelki dla psa Truelove Front-Line Premium Blossom",
        "Szelki dla psa Truelove Fron Line Blossom",
        "Szelki dla psa Truelove Fron Line Premium Blossom",
    },
    "Szelki dla psa Truelove Front Line Premium Cordura": {
        "Szelki dla psa Truelove Front Line Cordura",
        "Szelki dla psa Truelove FrontLine Premium Cordura",
        "Szelki dla psa Truelove FrontLine Cordura",
        "Szelki dla psa Truelove Front-Line Premium Cordura",
        "Szelki dla psa Truelove Front-Line Cordura",
        "Szelki dla psa Truelove Fron Line Premium Cordura",
        "Szelki dla psa Truelove Fron Line Cordura",
    },
}


def _build_alias_lookup() -> dict[str, str]:
    lookup: dict[str, str] = {}
    for canonical, aliases in _PRODUCT_ALIAS_GROUPS.items():
        variants = set(aliases)
        variants.add(canonical)
        for variant in variants:
            key = _normalize_alias_key(variant)
            lookup[key] = canonical
    return lookup


_PRODUCT_ALIAS_LOOKUP = _build_alias_lookup()


def resolve_product_alias(name: str) -> str:
    """Return canonical product name for *name* if an alias is known."""

    key = _normalize_alias_key(name)
    return _PRODUCT_ALIAS_LOOKUP.get(key, (name or "").strip())


# Backwards compatibility mapping that contains explicit alias -> canonical
# entries (without additional normalization).  New code should prefer
# ``resolve_product_alias`` which understands spelling variants.
PRODUCT_ALIASES = {
    alias: canonical
    for canonical, aliases in _PRODUCT_ALIAS_GROUPS.items()
    for alias in aliases
}
