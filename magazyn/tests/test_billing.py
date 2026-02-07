"""Testy jednostkowe dla allegro_api/billing.py.

Pokrywaja:
- Klasyfikacje typow billingowych (organic vs promoted)
- get_order_billing_summary() - agregacje oplat
- Wykrywanie sprzedazy promowanych (FSF/BRG)
- Szacowanie kosztu wysylki
"""
import pytest
from decimal import Decimal
from unittest.mock import patch, MagicMock

from magazyn.allegro_api.billing import (
    ORGANIC_COMMISSION_TYPES,
    PROMOTED_COMMISSION_TYPES,
    COMMISSION_TYPES,
    SHIPPING_TYPES,
    PROMO_TYPES,
    REFUND_TYPES,
    LISTING_TYPES,
    get_order_billing_summary,
)


class TestBillingTypeClassification:
    """Testy klasyfikacji typow billingowych."""

    def test_organic_contains_suc(self):
        assert "SUC" in ORGANIC_COMMISSION_TYPES

    def test_promoted_contains_fsf_brg(self):
        assert "FSF" in PROMOTED_COMMISSION_TYPES
        assert "BRG" in PROMOTED_COMMISSION_TYPES

    def test_commission_is_union(self):
        assert COMMISSION_TYPES == ORGANIC_COMMISSION_TYPES | PROMOTED_COMMISSION_TYPES

    def test_no_overlap_organic_promoted(self):
        assert ORGANIC_COMMISSION_TYPES & PROMOTED_COMMISSION_TYPES == set()

    def test_shipping_types_not_empty(self):
        assert len(SHIPPING_TYPES) > 0

    def test_promo_types_contains_fea_ads(self):
        assert "FEA" in PROMO_TYPES
        assert "ADS" in PROMO_TYPES


def _make_billing_entry(type_id, amount, type_name=None):
    """Helper - tworzy wpis billingowy w formacie API Allegro."""
    return {
        "type": {
            "id": type_id,
            "name": type_name or type_id,
        },
        "value": {
            "amount": str(amount),
            "currency": "PLN",
        },
    }


class TestGetOrderBillingSummary:
    """Testy agregacji get_order_billing_summary()."""

    @patch("magazyn.allegro_api.billing.fetch_billing_entries")
    def test_organic_sale_not_promoted(self, mock_fetch):
        """Sprzedaz organiczna (SUC) nie powinna byc oznaczona jako promowana."""
        mock_fetch.return_value = {
            "billingEntries": [
                _make_billing_entry("SUC", "-5.00", "Prowizja od sprzedazy"),
            ]
        }
        result = get_order_billing_summary("token", "order-123")

        assert result["success"] is True
        assert result["commission"] == Decimal("5.00")
        assert result["promoted_commission"] == Decimal("0")
        assert result["is_promoted_sale"] is False
        assert result["promotion_type"] is None

    @patch("magazyn.allegro_api.billing.fetch_billing_entries")
    def test_fsf_wyroznione(self, mock_fetch):
        """FSF (wyroznione) powinno ustawic is_promoted_sale i promotion_type."""
        mock_fetch.return_value = {
            "billingEntries": [
                _make_billing_entry("FSF", "-7.50", "Prowizja od wyroznionej"),
            ]
        }
        result = get_order_billing_summary("token", "order-456")

        assert result["success"] is True
        assert result["commission"] == Decimal("7.50")
        assert result["promoted_commission"] == Decimal("7.50")
        assert result["is_promoted_sale"] is True
        assert result["promotion_type"] == "wyroznione"

    @patch("magazyn.allegro_api.billing.fetch_billing_entries")
    def test_brg_allegro_ads(self, mock_fetch):
        """BRG (kampania ads) powinno ustawic promotion_type = allegro_ads."""
        mock_fetch.return_value = {
            "billingEntries": [
                _make_billing_entry("BRG", "-6.00", "Kampania"),
            ]
        }
        result = get_order_billing_summary("token", "order-789")

        assert result["is_promoted_sale"] is True
        assert result["promotion_type"] == "allegro_ads"
        assert result["promoted_commission"] == Decimal("6.00")

    @patch("magazyn.allegro_api.billing.fetch_billing_entries")
    def test_fsf_takes_priority_over_brg(self, mock_fetch):
        """Jesli jest FSF i BRG, promotion_type = wyroznione (FSF ma priorytet)."""
        mock_fetch.return_value = {
            "billingEntries": [
                _make_billing_entry("FSF", "-5.00"),
                _make_billing_entry("BRG", "-3.00"),
            ]
        }
        result = get_order_billing_summary("token", "order-mix")

        assert result["promotion_type"] == "wyroznione"
        assert result["promoted_commission"] == Decimal("8.00")
        assert result["commission"] == Decimal("8.00")

    @patch("magazyn.allegro_api.billing.fetch_billing_entries")
    def test_mixed_fees_aggregation(self, mock_fetch):
        """Test pelnej agregacji roznych typow oplat."""
        mock_fetch.return_value = {
            "billingEntries": [
                _make_billing_entry("SUC", "-10.00"),
                _make_billing_entry("LIS", "-0.50"),
                _make_billing_entry("HLB", "-8.99"),
                _make_billing_entry("FEA", "-2.00"),
                _make_billing_entry("REF", "5.00"),
            ]
        }
        result = get_order_billing_summary("token", "order-full")

        assert result["commission"] == Decimal("10.00")
        assert result["listing_fee"] == Decimal("0.50")
        assert result["shipping_fee"] == Decimal("8.99")
        assert result["promo_fee"] == Decimal("2.00")
        assert result["refunds"] == Decimal("5.00")
        assert result["total_fees"] == Decimal("21.49")

    @patch("magazyn.allegro_api.billing.fetch_billing_entries")
    def test_positive_amounts_ignored_for_fees(self, mock_fetch):
        """Dodatnie kwoty (wplywy) nie powinny byc liczone jako oplaty."""
        mock_fetch.return_value = {
            "billingEntries": [
                _make_billing_entry("SUC", "10.00"),  # dodatnia - nie jest oplata
            ]
        }
        result = get_order_billing_summary("token", "order-pos")

        assert result["commission"] == Decimal("0")

    @patch("magazyn.allegro_api.billing.fetch_billing_entries")
    def test_api_error_sets_success_false(self, mock_fetch):
        """Blad API powinien zwrocic success=False z komunikatem."""
        mock_fetch.side_effect = Exception("API timeout")

        result = get_order_billing_summary("token", "order-err")

        assert result["success"] is False
        assert "API timeout" in result["error"]

    @patch("magazyn.allegro_api.billing.fetch_billing_entries")
    def test_empty_entries(self, mock_fetch):
        """Brak wpisow billingowych zwraca zerowe wartosci."""
        mock_fetch.return_value = {"billingEntries": []}

        result = get_order_billing_summary("token", "order-empty")

        assert result["success"] is True
        assert result["total_fees"] == Decimal("0")
        assert result["is_promoted_sale"] is False
