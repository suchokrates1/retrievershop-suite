"""Testy przyrostowego sync katalogu Woo + skip no-op stock PUT."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from magazyn.services.woo_catalog_sync import (
    compute_family_fingerprint,
    family_needs_catalog_sync,
)
from magazyn.services.woo_stock_reconcile import reconcile_woo_stock


def test_family_needs_sync_when_unmapped():
    product = SimpleNamespace(
        id=1,
        woo_product_id=None,
        color="Czarny",
        category="Szelki",
        brand="Truelove",
        series="Tracker",
    )
    size = SimpleNamespace(id=10, barcode="590", size="L", quantity=2, woo_variation_id=None)
    db = MagicMock()
    with patch(
        "magazyn.services.woo_catalog_sync._collect_family_variants",
        return_value=[(product, size, None)],
    ):
        assert family_needs_catalog_sync(
            db, [product], snapshots={}, mode="incremental"
        )


def test_family_skips_when_fingerprint_matches():
    product = SimpleNamespace(
        id=1,
        woo_product_id=100,
        color="Czarny",
        category="Szelki",
        brand="Truelove",
        series="Tracker",
    )
    size = SimpleNamespace(
        id=10, barcode="590", size="L", quantity=2, woo_variation_id=201
    )
    offer = SimpleNamespace(
        price="99.00",
        title="Szelki",
        publication_status="ACTIVE",
        content_synced_at="2026-01-01T00:00:00+00:00",
    )
    db = MagicMock()
    variants = [(product, size, offer)]
    with patch(
        "magazyn.services.woo_catalog_sync._collect_family_variants",
        return_value=variants,
    ):
        fp = compute_family_fingerprint(db, [product])
        key = "szelki|truelove|tracker"
        assert not family_needs_catalog_sync(
            db, [product], snapshots={key: fp}, mode="incremental"
        )
        assert family_needs_catalog_sync(
            db, [product], snapshots={key: "old"}, mode="incremental"
        )
        assert family_needs_catalog_sync(
            db, [product], snapshots={key: fp}, mode="full"
        )


def test_reconcile_skips_put_when_stock_unchanged():
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
    stale_q = MagicMock()
    stale_q.filter.return_value.all.return_value = [size]
    barcodes_q = MagicMock()
    barcodes_q.filter.return_value = [("5901234567890",)]

    db1 = MagicMock()
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

    assert stats["updated"] == 0
    assert stats["unchanged"] == 1
    assert client.put.call_count == 0
