from .constants import ALL_SIZES, KNOWN_COLORS, PRODUCT_ALIASES

COLOR_ALIASES = {
    "czerwone": "czerwony",
    "niebieskie": "niebieski",
    "zielone": "zielony",
    "czarne": "czarny",
    "białe": "biały",
    "brązowe": "brązowy",
    "różowe": "różowy",
    "fioletowe": "fioletowy",
    "srebrne": "srebrny",
    "pomarańczowe": "pomarańczowy",
    "pomarańczowa": "pomarańczowy",
    "turkusowe": "turkusowy",
}


def normalize_color(color: str) -> str:
    if not color:
        return ""
    base = COLOR_ALIASES.get(color.lower(), color).lower()
    return base.capitalize()


def parse_product_info(item: dict) -> tuple[str, str, str]:
    """Return product name, size and color from an order item."""
    if not item:
        return "", "", ""

    name = item.get("name", "") or ""
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
        if len(words) >= 3:
            maybe_size = words[-1]
            if maybe_size.upper() in {s.upper() for s in ALL_SIZES}:
                size = maybe_size
                if not color:
                    color = words[-2]
                name = " ".join(words[:-2])
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

    name = name.strip()
    name = PRODUCT_ALIASES.get(name, name)
    color = normalize_color(color)
    return name, size, color
