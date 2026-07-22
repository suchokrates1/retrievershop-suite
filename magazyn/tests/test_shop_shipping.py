"""Testy kosztów wysyłki sklepu (InPost)."""

from decimal import Decimal
from types import SimpleNamespace

from magazyn.domain.shop_shipping import (
    estimate_shop_shipping_cost,
    extract_rate_from_shipment,
    get_stored_seller_shipping,
    resolve_parcel_size,
    store_seller_shipping_on_order,
)


def test_resolve_parcel_size():
    assert resolve_parcel_size("small") == "A"
    assert resolve_parcel_size("medium") == "B"
    assert resolve_parcel_size("large") == "C"


def test_estimate_locker_and_courier(monkeypatch):
    monkeypatch.setattr(
        "magazyn.domain.shop_shipping.settings_store.get",
        lambda key: None,
    )
    locker_order = SimpleNamespace(
        delivery_method="InPost Paczkomat",
        delivery_point_id="WAW1",
    )
    courier_order = SimpleNamespace(
        delivery_method="InPost Kurier",
        delivery_point_id=None,
    )
    locker = estimate_shop_shipping_cost(locker_order)
    courier = estimate_shop_shipping_cost(courier_order)
    assert locker["cost"] == Decimal("16.49")
    assert locker["channel"] == "locker"
    assert courier["cost"] == Decimal("19.49")
    assert courier["channel"] == "courier"


def test_store_and_read_seller_shipping():
    order = SimpleNamespace(products_json='[{"name": "X", "quantity": 1}]')
    store_seller_shipping_on_order(order, Decimal("16.49"), source="api")
    stored = get_stored_seller_shipping(order)
    assert stored is not None
    assert stored["cost"] == Decimal("16.49")
    assert stored["source"] == "api"


def test_extract_rate_from_shipment():
    details = {"selected_offer": {"rate": "16.49"}}
    assert extract_rate_from_shipment(details) == Decimal("16.49")
    assert extract_rate_from_shipment({"offers": [{"rate": 19.49}]}) == Decimal("19.49")
    assert extract_rate_from_shipment({}) is None
