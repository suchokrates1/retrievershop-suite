"""Testy jednostkowe dla allegro_helpers.py.

Pokrywaja:
- format_decimal() - formatowanie wartosci dziesietnych
- build_offer_label() - budowanie etykiet ofert
- build_inventory_list() - budowanie listy inventory
"""
from decimal import Decimal
from unittest.mock import MagicMock

from magazyn.allegro_helpers import format_decimal, build_offer_label, build_inventory_list


class TestFormatDecimal:
    """Testy formatowania wartosci dziesietnych."""

    def test_none_returns_none(self):
        assert format_decimal(None) is None

    def test_integer_value(self):
        assert format_decimal(Decimal("10")) == "10.00"

    def test_two_decimal_places(self):
        assert format_decimal(Decimal("99.99")) == "99.99"

    def test_more_decimal_places_truncated(self):
        result = format_decimal(Decimal("12.345"))
        # f-string :.2f uzywa bankowego zaokraglenia (ROUND_HALF_EVEN)
        assert result == "12.34" or result == "12.35"
        assert len(result.split(".")[-1]) == 2

    def test_zero(self):
        assert format_decimal(Decimal("0")) == "0.00"

    def test_negative_value(self):
        assert format_decimal(Decimal("-5.50")) == "-5.50"


class TestBuildOfferLabel:
    """Testy budowania etykiet ofert."""

    def test_product_with_color_and_size(self):
        product = MagicMock()
        product.name = "Szelki TreLove"
        product.color = "Czarny"
        size = MagicMock()
        size.size = "M"

        label = build_offer_label(product, size)
        assert "Szelki TreLove" in label
        assert "Czarny" in label
        assert "M" in label

    def test_product_without_color(self):
        product = MagicMock()
        product.name = "Smycz"
        product.color = None
        size = MagicMock()
        size.size = "L"

        label = build_offer_label(product, size)
        assert "Smycz" in label
        assert "L" in label

    def test_no_size(self):
        product = MagicMock()
        product.name = "Miska"
        product.color = "Czerwony"

        label = build_offer_label(product, None)
        assert "Miska" in label
        assert "Czerwony" in label


class TestBuildInventoryList:
    """Testy budowania listy inventory (wylacznie warianty rozmiarowe/SKU)."""

    def test_returns_list(self):
        db = MagicMock()
        db.query.return_value.join.return_value.order_by.return_value.all.return_value = []

        result = build_inventory_list(db)
        assert isinstance(result, list)

    def test_size_entry_has_required_keys(self):
        """Wpisy rozmiarowe musza zawierac wymagane klucze (bez rozroznienia typu -
        dopasowanie jest zawsze na poziomie rozmiaru/SKU)."""
        product = MagicMock()
        product.id = 1
        product.name = "Obroza"
        product.color = "Zielony"

        size = MagicMock()
        size.id = 10
        size.size = "S"
        size.barcode = "5901234567890"
        size.quantity = 5

        db = MagicMock()
        db.query.return_value.join.return_value.order_by.return_value.all.return_value = [(size, product)]

        result = build_inventory_list(db)

        assert len(result) == 1
        entry = result[0]
        assert "id" in entry
        assert "label" in entry
        assert "filter" in entry
        assert "type" not in entry
        assert "5901234567890" in entry["extra"]
        assert "5" in entry["extra"]

    def test_multiple_sizes_all_present(self):
        """Wszystkie warianty rozmiarowe zwrocone przez zapytanie trafiaja na liste."""
        product = MagicMock()
        product.id = 1
        product.name = "Test"
        product.color = None

        size_m = MagicMock()
        size_m.id = 10
        size_m.size = "M"
        size_m.barcode = None
        size_m.quantity = 3

        size_l = MagicMock()
        size_l.id = 11
        size_l.size = "L"
        size_l.barcode = None
        size_l.quantity = 0

        db = MagicMock()
        db.query.return_value.join.return_value.order_by.return_value.all.return_value = [
            (size_m, product),
            (size_l, product),
        ]

        result = build_inventory_list(db)

        assert [entry["id"] for entry in result] == [10, 11]
