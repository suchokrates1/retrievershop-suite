"""Testy Woo: webhook signature, import skip, print ShipX branch, fulfillment gate."""

from __future__ import annotations

import base64
import hashlib
import hmac
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from magazyn.domain.order_platform import is_allegro_order
from magazyn.services.label_agent_integrations import get_order_packages
from magazyn.services.order_fulfillment_sync import _sync_order_fulfillment
from magazyn.services.woo_inpost_labels import get_woo_inpost_packages
from magazyn.services.woo_order_sync import import_woo_order, verify_woo_webhook_signature


def test_verify_woo_webhook_signature_ok():
    body = b'{"id": 1}'
    secret = "test-secret"
    digest = hmac.new(secret.encode(), body, hashlib.sha256).digest()
    signature = base64.b64encode(digest).decode("ascii")
    with patch("magazyn.services.woo_order_sync.settings_store") as store:
        store.get.return_value = secret
        assert verify_woo_webhook_signature(body, signature) is True
        assert verify_woo_webhook_signature(body, "bad") is False


def test_import_woo_order_skips_pending():
    payload = {
        "id": 99,
        "status": "pending",
        "currency": "PLN",
        "total": "10.00",
        "billing": {"first_name": "A", "last_name": "B", "email": "a@b.c"},
        "shipping": {},
        "shipping_lines": [],
        "line_items": [],
        "meta_data": [],
    }
    result = import_woo_order(payload)
    assert result["skipped"] is True
    assert result["order_id"] == "woo_99"


def test_get_order_packages_routes_woo_to_shipx():
    agent = SimpleNamespace(logger=MagicMock())
    with patch(
        "magazyn.services.label_agent_integrations.get_woo_inpost_packages",
        return_value=[{"shipment_id": "1"}],
    ) as woo_fn:
        result = get_order_packages(
            agent,
            "woo_3415",
            get_shipment_details=MagicMock(),
            create_allegro_shipment=MagicMock(),
        )
    assert result == [{"shipment_id": "1"}]
    woo_fn.assert_called_once_with(agent, "woo_3415")


def test_sync_order_fulfillment_skips_non_allegro():
    order = SimpleNamespace(order_id="woo_3415", external_order_id="3415")
    assert _sync_order_fulfillment(MagicMock(), order, MagicMock()) == "skipped"
    assert is_allegro_order(order) is False


def test_woo_inpost_persists_shipment_id_before_label_wait():
    saved: dict[str, str] = {}
    agent = SimpleNamespace(
        logger=MagicMock(),
        last_order_data={"order_id": "woo_1", "customer": "X"},
        _load_state_value=lambda key: None,
        _save_state_value=lambda key, value: saved.__setitem__(key, value),
    )

    def _fake_create(order_data, *, on_shipment_created=None, wait_seconds=20.0):
        assert on_shipment_created is not None
        on_shipment_created("ship-early")
        assert saved.get("inpost_shipment:woo_1") == "ship-early"
        return {
            "shipment_id": "ship-early",
            "waybill": "TRACK1",
            "label_pdf": b"%PDF-1.4",
        }

    with (
        patch(
            "magazyn.inpost_api.create_shipment_and_label",
            side_effect=_fake_create,
        ),
        patch("magazyn.woocommerce_api.WooClient"),
        patch("magazyn.woocommerce_api.orders.update_order_tracking"),
    ):
        packages = get_woo_inpost_packages(agent, "woo_1")

    assert packages[0]["shipment_id"] == "ship-early"
    assert saved["inpost_shipment:woo_1"] == "ship-early"


def test_catalog_reuses_existing_product_images():
    from magazyn.services import woo_catalog_sync as sync_mod

    client = MagicMock()
    product = SimpleNamespace(id=1, name="Szelki", woo_product_id=55, category=None, brand=None, series=None, color=None)
    size = SimpleNamespace(
        id=10,
        product_id=1,
        barcode="5901234567890",
        size="L",
        quantity=2,
        woo_variation_id=100,
        product=product,
    )
    offer = SimpleNamespace(
        offer_id="OFF1",
        product_size_id=10,
        publication_status="ACTIVE",
        synced_at=None,
        description_html="<p>x</p>",
        image_urls='["https://cdn.example/a.jpg"]',
        title="Szelki L",
        price=99.0,
    )

    size_query = MagicMock()
    size_query.filter.return_value.all.return_value = [size]
    offer_query = MagicMock()
    offer_query.filter.return_value.order_by.return_value.first.return_value = offer

    db = MagicMock()
    db.query.side_effect = [size_query, offer_query]

    stats = {"products": 0, "variations": 0, "errors": 0, "skipped": 0}

    with (
        patch.object(sync_mod, "get_product_image_ids", return_value=[777]) as get_imgs,
        patch.object(sync_mod, "upload_product_image_from_url") as upload,
        patch.object(sync_mod, "build_product_attributes", return_value=[{"name": "Rozmiar", "options": ["L"]}]),
        patch.object(sync_mod, "ensure_product_category", return_value=None),
        patch.object(
            sync_mod,
            "create_or_update_variable_product",
            return_value={"id": 55},
        ) as upsert_product,
        patch.object(sync_mod, "upsert_variation", return_value={"id": 100}),
        patch.object(sync_mod, "sync_offer_content"),
    ):
        sync_mod._sync_one_product(
            db,
            client,
            product,
            refresh_content=False,
            stats=stats,
        )

    get_imgs.assert_called_once_with(client, 55)
    upload.assert_not_called()
    assert upsert_product.call_args.kwargs["image_ids"] == [777]
