"""Testy kanonicznych nazw Woo i short_description."""

from types import SimpleNamespace

from magazyn.services.woo_product_naming import (
    canonical_woo_product_name,
    sanitize_parent_product_title,
    short_description_plain,
)


def test_canonical_uses_product_name_not_allegro_size_color():
    product = SimpleNamespace(
        name="Szelki dla psa Truelove Front Line Premium",
        category="Szelki",
        brand="Truelove",
        series="Front Line Premium",
        color="fioletowe",
    )
    assert canonical_woo_product_name(
        product, fallback_title="Szelki guard L fioletowe"
    ) == "Szelki dla psa Truelove Front Line Premium — fioletowe"


def test_canonical_without_color_stays_base():
    product = SimpleNamespace(
        name="Smycz dla psa Truelove Handy",
        category="Smycze",
        brand="Truelove",
        series="Handy",
        color="",
    )
    assert canonical_woo_product_name(product) == "Smycz dla psa Truelove Handy"


def test_sanitize_strips_size_color_and_typos():
    assert (
        sanitize_parent_product_title(
            "Szelki dla psa Trelove Front Line Premium M czarne"
        )
        == "Szelki dla psa Truelove Front Line Premium"
    )
    assert "Fronr" not in sanitize_parent_product_title(
        "Szelki dla psa Truelove Fronr Line Premium"
    )


def test_short_description_plain_no_html_cut():
    html = "<p>" + ("słowo " * 80) + "</p>"
    short = short_description_plain(html, max_len=80)
    assert "<" not in short
    assert len(short) <= 81
    assert short.endswith("…")
