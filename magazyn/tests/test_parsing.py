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
