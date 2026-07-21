"""Kanoniczne nazwy i skroty SEO dla produktow Woo."""

from __future__ import annotations

import re
from html import unescape
from typing import Any, Optional

# Tokeny rozmiaru / koloru — nie powinny trafic do nazwy rodzica variable
_SIZE_TOKENS = {
    "xxs",
    "xs",
    "s",
    "m",
    "l",
    "xl",
    "xxl",
    "2xl",
    "3xl",
    "4xl",
    "uniwersalny",
}


def _strip_html(text: str) -> str:
    no_tags = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", unescape(no_tags)).strip()


def short_description_plain(description_html: str, *, max_len: int = 160) -> str:
    """Plain-text excerpt pod short_description (bez ucinania HTML w polowie tagu)."""
    plain = _strip_html(description_html)
    if len(plain) <= max_len:
        return plain
    cut = plain[: max_len - 1].rsplit(" ", 1)[0]
    return (cut or plain[: max_len - 1]).rstrip(".,;:") + "…"


def product_family_key(product: Any) -> tuple[str, str, str]:
    """Klucz rodziny Woo: category + brand + series (bez koloru)."""
    return (
        (getattr(product, "category", None) or "").strip().lower(),
        (getattr(product, "brand", None) or "").strip().lower(),
        (getattr(product, "series", None) or "").strip().lower(),
    )


def canonical_woo_product_name(product: Any, *, fallback_title: Optional[str] = None) -> str:
    """Nazwa rodzica variable: kategoria + marka + model — bez rozmiaru i koloru.

    Kolor jest atrybutem wariantu (scalanie kolorow w 1 parent). Preferuje
    ``Product.name``; ``fallback_title`` tylko gdy name puste.
    """
    name = (getattr(product, "name", None) or "").strip()
    if not name and fallback_title:
        name = str(fallback_title).strip()
    if not name:
        parts = [
            (getattr(product, "category", None) or "").strip(),
            "dla psa",
            (getattr(product, "brand", None) or "").strip(),
            (getattr(product, "series", None) or "").strip(),
        ]
        name = " ".join(p for p in parts if p and p != "dla psa")
        if "dla psa" not in name and (getattr(product, "category", None) or "").strip():
            cat = (product.category or "").strip()
            rest = " ".join(
                p
                for p in [
                    (getattr(product, "brand", None) or "").strip(),
                    (getattr(product, "series", None) or "").strip(),
                ]
                if p
            )
            name = f"{cat} dla psa {rest}".strip()

    return sanitize_parent_product_title(name)


def sanitize_parent_product_title(title: str) -> str:
    """Usun trailing rozmiar/kolor, em-dash color suffix i znane literowki marki."""
    name = (title or "").strip()
    if not name:
        return name

    # Literowki marki / modelu
    replacements = (
        ("Trelove", "Truelove"),
        ("Truelve", "Truelove"),
        ("Fronr", "Front"),
        ("ptemium", "Premium"),
        ("Ptemium", "Premium"),
        ("średnieho", "średniego"),
        ("srednieho", "sredniego"),
    )
    for bad, good in replacements:
        name = name.replace(bad, good)

    # Sufiks „ — kolor” / „ - kolor”
    name = re.sub(r"\s+[—–-]\s+\S+\s*$", "", name).strip()

    # Odcinaj z konca: rozmiar, potem kolor (jedno slowo)
    tokens = name.split()
    while tokens:
        last = tokens[-1]
        last_l = last.lower().rstrip(".,;")
        if last_l in _SIZE_TOKENS:
            tokens.pop()
            continue
        if _looks_like_color_token(last_l):
            tokens.pop()
            continue
        break
    return " ".join(tokens).strip(" -—–")


def _looks_like_color_token(token: str) -> bool:
    colors = {
        "czarny",
        "czarna",
        "czarne",
        "czarnych",
        "bialy",
        "biały",
        "biala",
        "biała",
        "biale",
        "białe",
        "czerwony",
        "czerwona",
        "czerwone",
        "czerwonw",
        "niebieski",
        "niebieska",
        "niebieskie",
        "zielony",
        "zielona",
        "zielone",
        "zolty",
        "żółty",
        "zolte",
        "żółte",
        "rozowy",
        "różowy",
        "rozowe",
        "różowe",
        "rozowa",
        "różowa",
        "fioletowy",
        "fioletowa",
        "fioletowe",
        "pomaranczowy",
        "pomarańczowy",
        "pomaranczowa",
        "pomarańczowa",
        "pomaranczowe",
        "pomarańczowe",
        "szary",
        "szara",
        "szare",
        "granatowy",
        "granatowa",
        "granatowe",
        "limonkowy",
        "limonkowa",
        "limonkowe",
        "turkusowy",
        "turkusowa",
        "turkusowe",
        "liliowy",
        "liliowa",
        "liliowe",
        "bezowy",
        "beżowy",
        "bezowe",
        "beżowe",
    }
    return token in colors


__all__ = [
    "canonical_woo_product_name",
    "product_family_key",
    "sanitize_parent_product_title",
    "short_description_plain",
]
