from magazyn.services.product_listing import filter_products, listing_category


def test_listing_category_prefers_legacy_name_over_misleading_category():
    product = {
        "category": "Szelki",
        "legacy_name": "Pasy samochodowe",
        "series": None,
    }
    assert listing_category(product) == "Pas samochodowe"


def test_filter_products_matches_legacy_name():
    products = [
        {
            "id": 45,
            "name": "Szelki dla psa Truelove",
            "legacy_name": "Pasy samochodowe",
            "listing_category": "Pas samochodowe",
            "display_name": "Truelove Szelki",
            "category": "Szelki",
            "brand": "Truelove",
            "series": None,
            "color": "Czarny",
            "sizes": {"Uniwersalny": 0},
        }
    ]

    assert filter_products(products, "Pas")
    assert filter_products(products, "samochodowe")
    assert not filter_products(products, "kamizelka")


def test_filter_products_matches_display_name():
    products = [
        {
            "id": 1,
            "name": "Szelki dla psa Truelove Front Line",
            "legacy_name": "",
            "display_name": "Front Line Szelki",
            "category": "Szelki",
            "brand": "Truelove",
            "series": "Front Line",
            "color": "Czarny",
            "sizes": {"M": 1},
        }
    ]

    assert filter_products(products, "Front Line")
