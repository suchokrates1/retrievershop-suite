"""Testy WooPayments fee helpers."""

from decimal import Decimal
from unittest.mock import MagicMock

from magazyn.woocommerce_api.client import WooClientError
from magazyn.woocommerce_api.payments import (
    classify_woo_payment_method,
    estimate_woo_payment_fee,
    get_order_payment_fees,
)


def test_classify_payment_methods():
    assert classify_woo_payment_method("Pobranie") == "cod"
    assert classify_woo_payment_method("cod") == "cod"
    assert classify_woo_payment_method("Przelewy24") == "p24"
    assert classify_woo_payment_method("woocommerce_payments") == "card"
    assert classify_woo_payment_method("Visa") == "card"


def test_estimate_card_and_p24(monkeypatch):
    monkeypatch.setattr(
        "magazyn.woocommerce_api.payments.settings_store.get",
        lambda key: None,
    )
    sale = Decimal("100.00")
    assert estimate_woo_payment_fee(sale, "card") == Decimal("2.50")  # 1.5 + 1
    assert estimate_woo_payment_fee(sale, "Przelewy24") == Decimal("2.90")  # 1.9 + 1
    assert estimate_woo_payment_fee(sale, "pobranie") == Decimal("0.00")


def test_get_order_payment_fees_from_api():
    client = MagicMock()
    client.get.return_value = [
        {
            "type": "charge",
            "fees": 250,
            "amount": 10000,
            "net_amount": 9750,
            "payment_method": {"type": "card"},
        }
    ]
    result = get_order_payment_fees(42, client=client)
    assert result["success"] is True
    assert result["fee_source"] == "api"
    assert result["fees"] == Decimal("2.50")
    assert result["amount"] == Decimal("100.00")
    assert result["payment_method"] == "card"


def test_get_order_payment_fees_cod_skips_api():
    client = MagicMock()
    result = get_order_payment_fees(7, payment_method="Pobranie", client=client)
    assert result["fees"] == Decimal("0.00")
    assert result["fee_source"] == "api"
    client.get.assert_not_called()


def test_get_order_payment_fees_fallback_on_error(monkeypatch):
    monkeypatch.setattr(
        "magazyn.woocommerce_api.payments.settings_store.get",
        lambda key: None,
    )
    client = MagicMock()
    client.get.side_effect = WooClientError("boom", status_code=404)
    result = get_order_payment_fees(
        99,
        sale_price=Decimal("100.00"),
        payment_method="card",
        client=client,
    )
    assert result["success"] is True
    assert result["fee_source"] == "estimated"
    assert result["fees"] == Decimal("2.50")
