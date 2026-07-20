from types import SimpleNamespace
from unittest.mock import MagicMock

from magazyn.services.woo_catalog_sync import _resolve_variable_parent_id
from magazyn.woocommerce_api import WooClientError


def test_resolve_keeps_variable_parent():
    client = MagicMock()
    client.get.return_value = {"id": 55, "type": "variable"}
    product = SimpleNamespace(id=1, woo_product_id=55, sizes=[])
    assert _resolve_variable_parent_id(client, product, 55) == 55


def test_resolve_variation_to_parent():
    client = MagicMock()
    client.get.return_value = {
        "id": 100,
        "type": "variation",
        "parent_id": 50,
        "sku": "5901234567890",
    }
    matched = SimpleNamespace(woo_variation_id=None, barcode="5901234567890")
    empty = SimpleNamespace(woo_variation_id=None, barcode=None)
    product = SimpleNamespace(id=1, woo_product_id=100, sizes=[empty, matched])
    assert _resolve_variable_parent_id(client, product, 100) == 50
    assert product.woo_product_id == 50
    assert matched.woo_variation_id == 100
    assert empty.woo_variation_id is None


def test_resolve_variation_without_sku_match_does_not_guess_size():
    client = MagicMock()
    client.get.return_value = {"id": 100, "type": "variation", "parent_id": 50, "sku": ""}
    size = SimpleNamespace(woo_variation_id=None, barcode=None)
    product = SimpleNamespace(id=1, woo_product_id=100, sizes=[size])
    assert _resolve_variable_parent_id(client, product, 100) == 50
    assert product.woo_product_id == 50
    assert size.woo_variation_id is None


def test_resolve_orphan_variation_clears_id():
    client = MagicMock()
    client.get.return_value = {"id": 100, "type": "variation", "parent_id": 0}
    product = SimpleNamespace(id=1, woo_product_id=100, sizes=[])
    assert _resolve_variable_parent_id(client, product, 100) is None
    assert product.woo_product_id is None


def test_resolve_missing_clears_id():
    client = MagicMock()
    client.get.side_effect = WooClientError("gone", status_code=404)
    product = SimpleNamespace(id=1, woo_product_id=999, sizes=[])
    assert _resolve_variable_parent_id(client, product, 999) is None
    assert product.woo_product_id is None
