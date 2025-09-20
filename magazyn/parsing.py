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
    known_colors = {color.lower() for color in KNOWN_COLORS}

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
        if not color and lower_word in known_colors:
            color = normalize_color(word)
            remaining_words.pop(index)

    name = " ".join(remaining_words).strip()
    name = PRODUCT_ALIASES.get(name, name)

    if not size:
        size = "Uniwersalny"

    return name, color, size
