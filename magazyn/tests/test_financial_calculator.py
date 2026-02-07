"""Testy jednostkowe dla domain/financial.py - FinancialCalculator.

Pokrywaja:
- get_packaging_cost() - pobieranie kosztu pakowania
- get_purchase_cost_for_product() - koszt zakupu produktu
- get_purchase_cost_for_order() - koszt zakupu zamowienia
- calculate_order_profit() - pelen rozklad zysku
"""
import pytest
from decimal import Decimal
from unittest.mock import MagicMock, patch, PropertyMock

from magazyn.domain.financial import FinancialCalculator, ProfitBreakdown


class TestPackagingCost:
    """Testy pobierania kosztu pakowania."""

    def test_default_packaging_cost(self):
        """Domyslny koszt pakowania to 0.16 PLN."""
        calc = FinancialCalculator(MagicMock(), settings_store=None)
        assert calc.get_packaging_cost() == Decimal("0.16")

    def test_custom_packaging_cost(self):
        """Koszt z ustawien powinien nadpisac domyslny."""
        settings = MagicMock()
        settings.get.return_value = "0.50"
        calc = FinancialCalculator(MagicMock(), settings_store=settings)
        assert calc.get_packaging_cost() == Decimal("0.50")

    def test_empty_setting_uses_default(self):
        """Puste ustawienie wraca do domyslnego."""
        settings = MagicMock()
        settings.get.return_value = None
        calc = FinancialCalculator(MagicMock(), settings_store=settings)
        assert calc.get_packaging_cost() == Decimal("0.16")


class TestPurchaseCostForProduct:
    """Testy kosztu zakupu produktu."""

    def test_returns_latest_batch_price(self):
        """Powinien zwrocic cene z najnowszej partii zakupu."""
        batch = MagicMock()
        batch.price = Decimal("25.00")

        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.first.return_value = batch

        calc = FinancialCalculator(db, settings_store=None)
        cost = calc.get_purchase_cost_for_product(product_id=1, size="M", quantity=2)
        assert cost == Decimal("50.00")

    def test_no_batch_returns_zero(self):
        """Brak partii zakupu zwraca 0."""
        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None

        calc = FinancialCalculator(db, settings_store=None)
        cost = calc.get_purchase_cost_for_product(product_id=99, size="XL")
        assert cost == Decimal("0")


class TestPurchaseCostForOrder:
    """Testy kosztu zakupu dla zamowienia."""

    def test_sums_costs_for_all_products(self):
        """Sumuje koszty zakupu dla wszystkich produktow w zamowieniu."""
        # Mock order products
        op1 = MagicMock()
        op1.product_size = MagicMock()
        op1.product_size.product = MagicMock()
        op1.product_size.product_id = 1
        op1.product_size.size = "M"
        op1.quantity = 1
        op1.auction_id = None

        op2 = MagicMock()
        op2.product_size = MagicMock()
        op2.product_size.product = MagicMock()
        op2.product_size.product_id = 2
        op2.product_size.size = "L"
        op2.quantity = 2
        op2.auction_id = None

        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = [op1, op2]

        calc = FinancialCalculator(db, settings_store=None)

        # Mock get_purchase_cost_for_product
        with patch.object(calc, 'get_purchase_cost_for_product') as mock_cost:
            mock_cost.side_effect = [Decimal("20.00"), Decimal("50.00")]
            total = calc.get_purchase_cost_for_order("order-123")

        assert total == Decimal("70.00")

    def test_no_products_returns_zero(self):
        """Zamowienie bez produktow zwraca 0."""
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = []

        calc = FinancialCalculator(db, settings_store=None)
        total = calc.get_purchase_cost_for_order("order-empty")
        assert total == Decimal("0")


class TestCalculateOrderProfit:
    """Testy pelnej kalkulacji zysku."""

    def test_profit_formula(self):
        """Zysk = cena sprzedazy - oplaty allegro - koszt zakupu - koszt pakowania."""
        order = MagicMock()
        order.payment_done = "100.00"
        order.order_id = "order-1"
        order.delivery_method = None
        order.external_order_id = None

        calc = FinancialCalculator(MagicMock(), settings_store=None)

        with patch.object(calc, 'get_allegro_fees', return_value=(Decimal("12.30"), 'estimated')):
            with patch.object(calc, 'get_purchase_cost_for_order', return_value=Decimal("30.00")):
                with patch.object(calc, 'get_packaging_cost', return_value=Decimal("0.16")):
                    result = calc.calculate_order_profit(order)

        assert isinstance(result, ProfitBreakdown)
        assert result.sale_price == Decimal("100.00")
        assert result.allegro_fees == Decimal("12.30")
        assert result.purchase_cost == Decimal("30.00")
        assert result.packaging_cost == Decimal("0.16")
        expected_profit = Decimal("100.00") - Decimal("12.30") - Decimal("30.00") - Decimal("0.16")
        assert result.profit == expected_profit
        assert result.fee_source == 'estimated'

    def test_profit_with_api_fees(self):
        """Zysk z rzeczywistymi oplatami z API."""
        order = MagicMock()
        order.payment_done = "200.00"
        order.order_id = "order-2"
        order.delivery_method = "InPost"
        order.external_order_id = "ext-uuid-123"

        calc = FinancialCalculator(MagicMock(), settings_store=None)

        with patch.object(calc, 'get_allegro_fees', return_value=(Decimal("25.50"), 'api')):
            with patch.object(calc, 'get_purchase_cost_for_order', return_value=Decimal("60.00")):
                with patch.object(calc, 'get_packaging_cost', return_value=Decimal("0.16")):
                    result = calc.calculate_order_profit(order)

        assert result.fee_source == 'api'
        assert result.profit == Decimal("200.00") - Decimal("25.50") - Decimal("60.00") - Decimal("0.16")

    def test_zero_payment_profit(self):
        """Zamowienie z zerowa platnoscia."""
        order = MagicMock()
        order.payment_done = 0
        order.order_id = "order-zero"
        order.delivery_method = None
        order.external_order_id = None

        calc = FinancialCalculator(MagicMock(), settings_store=None)

        with patch.object(calc, 'get_allegro_fees', return_value=(Decimal("0"), 'estimated')):
            with patch.object(calc, 'get_purchase_cost_for_order', return_value=Decimal("0")):
                result = calc.calculate_order_profit(order)

        assert result.profit == Decimal("0") - Decimal("0.16")
