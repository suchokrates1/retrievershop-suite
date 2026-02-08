from __future__ import annotations

import re
import unicodedata

ALL_SIZES = ["XS", "S", "M", "L", "XL", "2XL", "Uniwersalny"]

# Product categories
PRODUCT_CATEGORIES = [
    "Szelki",
    "Smycz",
    "Pas bezpieczeństwa",
    "Obroża",
]

# Known brands
PRODUCT_BRANDS = [
    "Truelove",
    "Julius-K9",
    "Ruffwear",
    "Hurtta",
]

# Product series (mainly Truelove)
PRODUCT_SERIES = [
    "Front Line Premium",
    "Front Line",
    "Active",
    "Blossom",
    "Tropical",
    "Lumen",
    "Amor",
    "Classic",
    "Neon",
    "Reflective",
]

# Common color names that may appear in product titles.  They are stored in
# lowercase form to simplify comparisons when parsing strings.
KNOWN_COLORS = [
    "czerwony",
    "czerwone",
    "niebieski",
    "niebieskie",
    "zielony",
    "zielone",
    "czarny",
    "czarne",
    "biały",
    "białe",
    "brązowy",
    "brązowe",
    "różowy",
    "różowe",
    "różow",
    "róż",
    "fioletowy",
    "fioletowe",
    "srebrny",
    "srebrne",
    "pomarańczowy",
    "pomarańczowe",
    "pomarańczowa",
    "turkusowy",
    "turkusowe",
    "granatowy",
    "granatowe",
    "granatowa",
    "szary",
    "szare",
    "żółty",
    "żółte",
    "żółta",
    "limonkowy",
    "limonkowe",
    "limonkowa",
]

# Regex rules used to normalize product titles and alias lookups.  The patterns
# are applied in order which allows the more specific replacements (e.g. with
# "Premium") to run before the general ones.
_PRODUCT_TITLE_REPLACEMENTS = [
    # Literowki w nazwie marki
    (re.compile(r"\btruelobve\b", re.IGNORECASE), "Truelove"),
    (re.compile(r"\btuelove\b", re.IGNORECASE), "Truelove"),
    (re.compile(r"\btrelove\b", re.IGNORECASE), "Truelove"),
    # Literowki w "Front"
    (re.compile(r"\bfron\b", re.IGNORECASE), "Front"),
    (re.compile(r"\bfrone\b", re.IGNORECASE), "Front"),
    (re.compile(r"\bftont\b", re.IGNORECASE), "Front"),
    (
        re.compile(r"\bfront[\s-]*line\s+premium\b", re.IGNORECASE),
        "Front Line Premium",
    ),
    (re.compile(r"\bfront[\s-]*line\b", re.IGNORECASE), "Front Line"),
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
