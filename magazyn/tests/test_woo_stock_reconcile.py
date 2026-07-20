"""Testy push stanu Woo i reconcile SKU."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from magazyn.services.stock_adjust import apply_stock_adjustment
from magazyn.services.woo_stock_reconcile import reconcile_woo_stock


def test_apply_stock_adjustment_pushes_woo_when_mapped():
    size = SimpleNamespace(
        id=10,
        product_id=1,
        size="L",
        quantity=5,
        stock_value=50,
        woo_variation_id=99,
    )
    with patch("magazyn.services.woo_catalog_sync.maybe_push_woo_stock") as push_fn:
        old, new = apply_stock_adjustment(size, delta=-1, reason="test")
    assert old == 5
    assert new == 4
    push_fn.assert_called_once_with(10, quantity=4)


def test_apply_stock_adjustment_skips_push_when_unmapped():
    size = SimpleNamespace(
        id=10,
        product_id=1,
        size="L",
        quantity=5,
        stock_value=50,
        woo_variation_id=None,
    )
    with patch("magazyn.services.woo_catalog_sync.maybe_push_woo_stock") as push_fn:
        apply_stock_adjustment(size, delta=-1, reason="test")
    push_fn.assert_not_called()


def test_reconcile_dedupes_duplicate_sku():
    client = MagicMock()
    woo_index = {
        "5901234567890": [
            {
                "parent_id": 100,
                "variation_id": 201,
                "product_id": 201,
                "type": "variation",
                "status": "publish",
                "qty": 9,
                "orphan": False,
            },
            {
                "parent_id": 101,
                "variation_id": 202,
                "product_id": 202,
                "type": "variation",
                "status": "publish",
                "qty": 3,
                "orphan": False,
            },
        ]
    }
    size = SimpleNamespace(
        id=1,
        barcode="5901234567890",
        quantity=2,
        size="M",
        woo_variation_id=201,
        product=SimpleNamespace(woo_product_id=100),
    )

    sizes_q = MagicMock()
    sizes_q.filter.return_value.all.return_value = [size]
    barcodes_q = MagicMock()
    barcodes_q.filter.return_value = [("5901234567890",)]

    db1 = MagicMock()
    db1.query.return_value = sizes_q
    db2 = MagicMock()
    db2.query.return_value = barcodes_q

    sessions = [
        MagicMock(__enter__=MagicMock(return_value=db1), __exit__=MagicMock(return_value=False)),
        MagicMock(__enter__=MagicMock(return_value=db2), __exit__=MagicMock(return_value=False)),
    ]

    with (
        patch("magazyn.services.woo_stock_reconcile.WooClient", return_value=client),
        patch("magazyn.services.woo_stock_reconcile._index_woo_by_sku", return_value=woo_index),
        patch("magazyn.services.woo_stock_reconcile.get_session", side_effect=sessions),
    ):
        stats = reconcile_woo_stock(dry_run=False)

    assert stats["updated"] == 1
    assert stats["deduped"] == 1
    put_paths = [c.args[0] for c in client.put.call_args_list]
    assert any("variations/201" in p for p in put_paths)
    assert any("variations/202" in p for p in put_paths)


def test_reconcile_clears_stale_duplicate_variation_mapping():
    client = MagicMock()
    woo_index = {
        "5901234567890": [
            {
                "parent_id": 100,
                "variation_id": 201,
                "product_id": 201,
                "type": "variation",
                "status": "publish",
                "qty": 2,
                "orphan": False,
            }
        ]
    }
    owner = SimpleNamespace(
        id=1,
        barcode="5901234567890",
        quantity=2,
        size="M",
        woo_variation_id=201,
        product=SimpleNamespace(woo_product_id=100),
    )
    stale = SimpleNamespace(
        id=2,
        barcode=None,
        quantity=0,
        size="XS",
        woo_variation_id=201,
        product=SimpleNamespace(woo_product_id=100),
    )

    sizes_q = MagicMock()
    sizes_q.filter.return_value.all.return_value = [owner]
    stale_q = MagicMock()
    stale_q.filter.return_value.all.return_value = [owner, stale]
    barcodes_q = MagicMock()
    barcodes_q.filter.return_value = [("5901234567890",)]

    db1 = MagicMock()
    # first query: sizes with barcode; second: stale mappings cleanup
    db1.query.side_effect = [sizes_q, stale_q]
    db2 = MagicMock()
    db2.query.return_value = barcodes_q

    sessions = [
        MagicMock(__enter__=MagicMock(return_value=db1), __exit__=MagicMock(return_value=False)),
        MagicMock(__enter__=MagicMock(return_value=db2), __exit__=MagicMock(return_value=False)),
    ]

    with (
        patch("magazyn.services.woo_stock_reconcile.WooClient", return_value=client),
        patch("magazyn.services.woo_stock_reconcile._index_woo_by_sku", return_value=woo_index),
        patch("magazyn.services.woo_stock_reconcile.get_session", side_effect=sessions),
    ):
        stats = reconcile_woo_stock(dry_run=False)

    assert stale.woo_variation_id is None
    assert owner.woo_variation_id == 201
    assert stats["remapped"] >= 1
