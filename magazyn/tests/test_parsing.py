import pytest

from magazyn.parsing import normalize_color, parse_offer_title


@pytest.mark.parametrize(
    ("title", "expected_size"),
    [
        ("Smycz róż", "Uniwersalny"),
        ("Smycz różowe", "Uniwersalny"),
        ("Smycz różowiutkie", "Uniwersalny"),
        ("Smycz rozowy M", "M"),
        ("Smycz różowe L", "L"),
    ],
)
def test_parse_offer_title_detects_pink_variants(title, expected_size):
    name, color, size = parse_offer_title(title)

    assert name == "Smycz"
    assert color == "Różowy"
    assert size == expected_size


@pytest.mark.parametrize(
    "value",
    [
        "róż",
        "różowe",
        "różowa",
        "różowiutkie",
        "rozowiutkie",
    ],
)
def test_normalize_color_returns_canonical_form(value):
    assert normalize_color(value) == "Różowy"


@pytest.mark.parametrize(
    "title, expected_name, expected_color, expected_size",
    [
        (
            "Mega okazja! Truelove Lumen dla aktywnych psów czerwone M",
            "Szelki dla psa Truelove Lumen",
            "Czerwony",
            "M",
        ),
        (
            "Wyprzedaż FRONT LINE PREMIUM Tropical turkusowy komplet",
            "Szelki dla psa Truelove Tropical",
            "Turkusowy",
            "Uniwersalny",
        ),
        (
            "Nowe Adventure Dog szelki blossom różowe L",
            "Szelki dla psa Truelove Adventure Dog",
            "Różowy",
            "L",
        ),
    ],
)
def test_parse_offer_title_prefers_known_model_keywords(
    title, expected_name, expected_color, expected_size
):
    name, color, size = parse_offer_title(title)

    assert name == expected_name
    assert color == expected_color
    assert size == expected_size
