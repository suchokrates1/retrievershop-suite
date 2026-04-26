"""Dopasowanie pozycji faktur do wariantow produktow."""

from __future__ import annotations

import re


def _extract_model_series(name: str) -> str:
    """Extract model series name from product name."""
    if not name:
        return ""
    name_lower = name.lower()
    model_series = [
        "front line premium",
        "front line",
        "tropical",
        "active",
        "outdoor",
        "classic",
        "comfort",
        "sport",
        "easy walk",
        "lumen",
        "amor",
        "blossom",
        "neon",
        "reflective",
        "dogi",
        "adventure",
        "handy",
    ]

    for series in model_series:
        if series in name_lower:
            return series
    return ""


def _parse_tiptop_sku(sku: str) -> dict:
    """Parse TipTop SKU to extract series, size, and color."""
    if not sku or not sku.startswith("TL-"):
        return {}

    parts = sku.split("-")
    if len(parts) < 4:
        return {}

    series_map = {
        "frolin-prem": "front line premium",
        "frolin": "front line",
        "tropic": "tropical",
        "tropi": "tropical",
        "active": "active",
        "outdoo": "outdoor",
        "classic": "classic",
        "comfort": "comfort",
        "sport": "sport",
        "lumen": "lumen",
        "dogi": "dogi",
        "advent": "adventure",
        "blossom": "blossom",
        "amor": "amor",
        "neon": "neon",
        "handy": "handy",
    }
    color_map = {
        "CZA": "czarny",
        "CZE": "czerwony",
        "BRA": "brązowy",
        "ROZ": "różowy",
        "POM": "pomarańczowy",
        "TUR": "turkusowy",
        "BIA": "biały",
        "NIE": "niebieski",
        "ZIE": "zielony",
        "SZA": "szary",
        "FIO": "fioletowy",
        "ZOL": "żółty",
        "LIM": "limonkowy",
    }
    size_aliases = {"XXL": "2XL", "XXXL": "3XL"}

    if len(parts) >= 5:
        color_code = parts[-1]
        size = parts[-2]
        series_parts = parts[2:-2]
    elif len(parts) == 4:
        color_code = ""
        size = parts[-1]
        series_parts = parts[2:-1]
    else:
        return {}

    series_code = "-".join(series_parts)
    size_upper = size.upper()
    return {
        "series": series_map.get(series_code, ""),
        "size": size_aliases.get(size_upper, size_upper),
        "color": color_map.get(color_code.upper(), "") if color_code else "",
        "color_code": color_code.upper() if color_code else "",
    }


def _extract_category(name: str) -> str:
    """Extract product category from name."""
    if not name:
        return ""
    name_lower = name.lower()
    if "smycz" in name_lower:
        return "Smycz"
    if "pas" in name_lower and ("bezpiecz" in name_lower or "samochodow" in name_lower):
        return "Pas bezpieczeństwa"
    if "obroża" in name_lower or "obroza" in name_lower or "obrozy" in name_lower:
        return "Obroża"
    if "szelki" in name_lower or "szelek" in name_lower:
        return "Szelki"
    return ""


def _match_by_tiptop_sku(sku: str, ps_list, row_name: str = "") -> tuple:
    """Match product by parsing TipTop SKU and finding exact match."""
    parsed = _parse_tiptop_sku(sku)
    if not parsed or not parsed.get("series"):
        return None, None, None

    target_series = parsed["series"]
    target_size = parsed.get("size", "").upper()
    target_color = parsed.get("color", "").lower()
    row_category = _extract_category(row_name)

    for product_size in ps_list:
        ps_series = _extract_model_series(product_size.name)
        ps_size = (product_size.size or "").upper()
        ps_color = (product_size.color or "").lower()
        ps_category = getattr(product_size, "category", "") or _extract_category(product_size.name)

        if row_category and ps_category and row_category != ps_category:
            continue
        if ps_series != target_series:
            continue
        if ps_size != target_size:
            continue
        if target_color and ps_color:
            if target_color not in ps_color and ps_color not in target_color:
                if target_color[:4] != ps_color[:4]:
                    continue

        return product_size.ps_id, f"{product_size.name} ({product_size.color}) {product_size.size}", "sku"

    return None, None, None


def _normalize_name(name: str) -> set:
    """Extract key words from product name for fuzzy matching."""
    if not name:
        return set()
    name = name.lower()
    filler_words = {
        "dla", "psa", "psy", "kota", "kotów", "szelki", "smycz", "obroża",
        "profesjonalne", "profesjonalny", "guard", "pro", "plus",
        "z", "od", "do", "na", "w", "i", "a", "o", "ze", "bez",
        "odpinanym", "odpinany", "przodem", "przód", "tyłem", "tył",
        "nowy", "nowa", "nowe", "nowych", "model", "wersja", "typ",
        "mały", "mała", "małe", "duży", "duża", "duże", "średni", "średnia",
        "easy", "walk",
    }
    words = re.findall(r"[a-zA-ZąćęłńóśźżĄĆĘŁŃÓŚŹŻ]+", name)
    return {word for word in words if word not in filler_words and len(word) > 2}


def _fuzzy_match_product(row_name: str, row_color: str, row_size: str, ps_list) -> tuple:
    """Try to fuzzy match a product based on name similarity."""
    if not row_name:
        return None, None, None

    row_color_lower = (row_color or "").lower().strip()
    row_size_upper = (row_size or "").upper().strip()
    row_key_words = _normalize_name(row_name)
    row_series = _extract_model_series(row_name)
    row_category = _extract_category(row_name)

    if not row_key_words:
        return None, None, None

    best_match = None
    best_score = 0

    for product_size in ps_list:
        ps_color_lower = (product_size.color or "").lower().strip()
        ps_size_upper = (product_size.size or "").upper().strip()
        ps_series = _extract_model_series(product_size.name)
        ps_category = getattr(product_size, "category", "") or _extract_category(product_size.name)

        if row_category and ps_category and row_category != ps_category:
            continue
        if row_size_upper and ps_size_upper and row_size_upper != ps_size_upper:
            continue
        if row_series and ps_series and row_series != ps_series:
            continue

        color_match = False
        if not row_color_lower or not ps_color_lower:
            color_match = True
        elif row_color_lower in ps_color_lower or ps_color_lower in row_color_lower:
            color_match = True
        elif row_color_lower[:4] == ps_color_lower[:4]:
            color_match = True

        if not color_match:
            continue

        ps_key_words = _normalize_name(product_size.name)
        if not ps_key_words:
            continue

        common_words = row_key_words & ps_key_words
        if not common_words:
            continue

        total_words = len(row_key_words | ps_key_words)
        score = len(common_words) / total_words if total_words > 0 else 0
        if row_series and ps_series and row_series == ps_series:
            score += 0.5
        if "truelove" in row_key_words and "truelove" in ps_key_words:
            score += 0.2
        if row_size_upper and row_size_upper == ps_size_upper:
            score += 0.3

        if score > best_score and score >= 0.5:
            best_score = score
            best_match = product_size

    if best_match:
        return best_match.ps_id, f"{best_match.name} ({best_match.color}) {best_match.size}", "fuzzy"

    return None, None, None


__all__ = [
    "_extract_category",
    "_extract_model_series",
    "_fuzzy_match_product",
    "_match_by_tiptop_sku",
    "_normalize_name",
    "_parse_tiptop_sku",
]