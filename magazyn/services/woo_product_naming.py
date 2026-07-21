"""Kanoniczne nazwy i skroty SEO dla produktow Woo."""

from __future__ import annotations

import re
from html import escape, unescape
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


_LEAD_START = "<!-- rs-woo-lead -->"
_LEAD_END = "<!-- /rs-woo-lead -->"

_CATEGORY_BLURB = {
    "szelki": "wygodne szelki na codzienne spacery i trening",
    "smycz": "smycz do codziennych spacerów i treningu",
    "smycze": "smycz do codziennych spacerów i treningu",
    "obroza": "obroża dopasowana do stylu spaceru",
    "obroże": "obroża dopasowana do stylu spaceru",
    "pasy bezpieczeństwa": "pas bezpieczeństwa do przewozu psa w aucie",
    "pas bezpieczeństwa": "pas bezpieczeństwa do przewozu psa w aucie",
    "saszetki": "saszetka na smakołyki i akcesoria",
    "pas trekkingowy": "pas biodrowy do biegania i dogtrekkingu",
    "kapok": "kamizelka / kapok dla psa",
    "kamizelka": "kamizelka dla psa",
    "amortyzator": "amortyzator do smyczy — mniej szarpnięć",
    "linka": "linka treningowa dla psa",
}

_SKIP_SENTENCE = re.compile(
    r"(kup teraz|allegro smart|darmowa dostawa od|raty |odwiedz|kliknij|"
    r"zobacz inne|najniższa cena|promocja|gratis|kod rabat)",
    re.I,
)


def _split_sentences(plain: str) -> list[str]:
    parts = re.split(r"(?<=[.!?…])\s+", plain)
    out: list[str] = []
    for part in parts:
        s = part.strip()
        if len(s) < 40 or len(s) > 220:
            continue
        if _SKIP_SENTENCE.search(s):
            continue
        if s.count(" ") < 5:
            continue
        out.append(s.rstrip())
    return out


def build_woo_lead(
    product: Any,
    description_html: str = "",
    *,
    colors: Optional[list[str]] = None,
    sizes: Optional[list[str]] = None,
) -> str:
    """Krotki lead PL (2–4 zdania) z faktow produktu + fragmentu opisu Allegro.

    Nie wymysla parametrow technicznych — tylko nazwa/kategoria/warianty
    oraz wyciagniete zdania z istniejacego opisu.
    """
    name = canonical_woo_product_name(product)
    category = (getattr(product, "category", None) or "").strip()
    brand = (getattr(product, "brand", None) or "").strip() or "Truelove"
    blurb = _CATEGORY_BLURB.get(category.lower(), "")

    sentences: list[str] = []
    if blurb:
        sentences.append(f"{name} — {blurb} marki {brand}.")
    else:
        sentences.append(f"{name} marki {brand}.")

    color_list = [c for c in (colors or []) if c]
    size_list = [s for s in (sizes or []) if s]
    variant_bits: list[str] = []
    if color_list:
        shown = ", ".join(color_list[:6])
        more = f" (+{len(color_list) - 6})" if len(color_list) > 6 else ""
        variant_bits.append(f"kolory: {shown}{more}")
    if size_list:
        variant_bits.append("rozmiary: " + ", ".join(size_list))
    if variant_bits:
        sentences.append("Dostępne " + "; ".join(variant_bits) + ".")

    for extracted in _split_sentences(_strip_html(description_html))[:2]:
        # unikaj duplikatu nazwy
        if name.lower()[:20] in extracted.lower() and len(sentences) >= 2:
            continue
        sentences.append(extracted)
        if len(sentences) >= 4:
            break

    if len(sentences) < 3:
        sentences.append(
            "Wysyłka z Legnicy — zamów do 16:00, zwykle paczka jutro (InPost, dostawa 0 zł)."
        )

    return " ".join(sentences[:4])


def strip_woo_lead(description_html: str) -> str:
    """Usun poprzedni blok leada z opisu Woo/Allegro."""
    html = description_html or ""
    if _LEAD_START not in html:
        return html
    pattern = re.compile(
        re.escape(_LEAD_START) + r".*?" + re.escape(_LEAD_END),
        re.I | re.S,
    )
    return pattern.sub("", html).lstrip()


def apply_woo_lead_to_description(description_html: str, lead_plain: str) -> str:
    """Wstaw lead HTML nad opisem Allegro (z markerem idempotentnym)."""
    body = strip_woo_lead(description_html or "")
    lead = (lead_plain or "").strip()
    if not lead:
        return body
    block = (
        f'{_LEAD_START}<div class="rs-woo-lead"><p>{escape(lead)}</p></div>{_LEAD_END}\n'
    )
    if body.strip():
        return block + body
    return block


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
    "apply_woo_lead_to_description",
    "build_woo_lead",
    "canonical_woo_product_name",
    "product_family_key",
    "sanitize_parent_product_title",
    "short_description_plain",
    "strip_woo_lead",
]
