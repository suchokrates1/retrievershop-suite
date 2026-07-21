"""Testy kategorii i atrybutow Woo z magazynu."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from magazyn.woocommerce_api.attributes import build_product_attributes, clear_attribute_cache
from magazyn.woocommerce_api.categories import (
    clear_category_cache,
    ensure_product_category,
    resolve_category_name,
)


def test_resolve_category_name_aliases():
    assert resolve_category_name("Smycz") == "Smycze"
    assert resolve_category_name("Pas bezpieczeństwa") == "Pasy bezpieczeństwa"
    assert resolve_category_name("Pas samochodowy") == "Pasy bezpieczeństwa"
    assert resolve_category_name("Pasy samochodowe") == "Pasy bezpieczeństwa"
    assert resolve_category_name("Szelki") == "Szelki"
    assert resolve_category_name("Obroża") == "Obroża"
    assert resolve_category_name(None) is None
    assert resolve_category_name("  ") is None


def test_ensure_product_category_reuses_existing():
    clear_category_cache()
    client = MagicMock()
    client.get.return_value = [
        {"id": 83, "name": "Smycze", "slug": "smycze"},
    ]
    cat_id = ensure_product_category(client, "Smycz")
    assert cat_id == 83
    client.post.assert_not_called()
    # cache hit
    assert ensure_product_category(client, "Smycz") == 83
    assert client.get.call_count == 1


def test_ensure_product_category_creates_when_missing():
    clear_category_cache()
    client = MagicMock()
    client.get.return_value = []
    client.post.return_value = {"id": 99, "name": "Obroża", "slug": "obroza"}
    cat_id = ensure_product_category(client, "Obroża")
    assert cat_id == 99
    payload = client.post.call_args.kwargs["json"]
    assert payload["name"] == "Obroża"
    assert payload["slug"] == "obroza"


def test_build_product_attributes_includes_brand_series_color_size():
    clear_attribute_cache()
    client = MagicMock()

    def _attrs_get(path, params=None):
        if path.endswith("/attributes") and "/terms" not in path:
            return [
                {"id": 1, "name": "Kolor"},
                {"id": 2, "name": "Rozmiar"},
            ]
        return []

    def _attrs_post(path, json=None):
        if path.endswith("/attributes") and "/terms" not in path:
            name = json["name"]
            return {"id": {"Marka": 10, "Seria": 11}[name], "name": name}
        return {"id": 100, "name": json["name"]}

    client.get.side_effect = _attrs_get
    client.post.side_effect = _attrs_post

    attrs = build_product_attributes(
        client,
        brand="Truelove",
        series="Front Line",
        colors=["Czarny", "Czerwony"],
        size_options=["L", "XL"],
    )
    by_key = {(a.get("id") or a.get("name")): a for a in attrs}
    assert by_key[10]["options"] == ["Truelove"]
    assert by_key[10]["variation"] is False
    assert by_key[11]["options"] == ["Front Line"]
    assert by_key[1]["options"] == ["Czarny", "Czerwony"]
    assert by_key[1]["variation"] is True
    assert by_key[2]["options"] == ["L", "XL"]
    assert by_key[2]["variation"] is True


def test_sync_one_product_sends_categories_and_attributes():
    from magazyn.services import woo_catalog_sync as sync_mod

    client = MagicMock()
    product = SimpleNamespace(
        id=1,
        name="Szelki",
        woo_product_id=55,
        category="Szelki",
        brand="Truelove",
        series="Front Line",
        color="Czarny",
    )
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
        image_urls="[]",
        title="Szelki L",
        price=99.0,
    )

    size_query = MagicMock()
    size_query.filter.return_value.all.return_value = [size]
    offer_query = MagicMock()
    offer_query.filter.return_value.order_by.return_value.first.return_value = offer
    db = MagicMock()
    # _collect_family_variants: sizes query, then ACTIVE offer, (no fallback if found)
    db.query.side_effect = [size_query, offer_query]

    stats = {"products": 0, "variations": 0, "errors": 0, "skipped": 0}

    with (
        patch.object(sync_mod, "_resolve_variable_parent_id", return_value=55),
        patch.object(sync_mod, "build_product_attributes", return_value=[{"id": 2, "options": ["L"]}]) as build_attrs,
        patch.object(sync_mod, "ensure_product_category", return_value=53) as ensure_cat,
        patch.object(sync_mod, "get_product_image_ids", return_value=[777]),
        patch.object(sync_mod, "upload_product_image_from_url") as upload,
        patch.object(
            sync_mod,
            "create_or_update_variable_product",
            return_value={"id": 55},
        ) as upsert_product,
        patch.object(sync_mod, "upsert_variation", return_value={"id": 100}) as upsert_var,
        patch.object(sync_mod, "sync_offer_content"),
        patch.object(sync_mod, "maybe_push_woo_stock"),
    ):
        sync_mod._sync_one_product(
            db,
            client,
            product,
            refresh_content=False,
            stats=stats,
        )

    ensure_cat.assert_called_once_with(client, "Szelki")
    build_attrs.assert_called_once()
    ba_kwargs = build_attrs.call_args.kwargs
    assert ba_kwargs["colors"] == ["Czarny"]
    assert upsert_product.call_args.kwargs["category_ids"] == [53]
    assert upsert_product.call_args.kwargs["attributes"] == [{"id": 2, "options": ["L"]}]
    assert upsert_var.call_args.kwargs["color"] == "Czarny"
    assert upsert_var.call_args.kwargs["size"] == "L"
    upload.assert_not_called()


def test_sync_one_family_shares_parent_across_colors():
    from magazyn.services import woo_catalog_sync as sync_mod

    client = MagicMock()
    black = SimpleNamespace(
        id=1,
        name="Szelki dla psa Truelove Front Line",
        woo_product_id=10,
        category="Szelki",
        brand="Truelove",
        series="Front Line",
        color="czarne",
    )
    orange = SimpleNamespace(
        id=2,
        name="Szelki dla psa Truelove Front Line",
        woo_product_id=20,
        category="Szelki",
        brand="Truelove",
        series="Front Line",
        color="pomarańczowe",
    )
    size_b = SimpleNamespace(
        id=11, product_id=1, barcode="EAN-B", size="L", quantity=1, woo_variation_id=101, product=black
    )
    size_o = SimpleNamespace(
        id=12, product_id=2, barcode="EAN-O", size="L", quantity=2, woo_variation_id=102, product=orange
    )
    offer_b = SimpleNamespace(
        offer_id="OB",
        publication_status="ACTIVE",
        synced_at=None,
        description_html="<p>desc black</p>",
        image_urls='["https://img/b.jpg"]',
        price="100",
    )
    offer_o = SimpleNamespace(
        offer_id="OO",
        publication_status="ACTIVE",
        synced_at=None,
        description_html="<p>x</p>",
        image_urls="[]",
        price="110",
    )

    size_q1 = MagicMock()
    size_q1.filter.return_value.all.return_value = [size_b]
    offer_q1 = MagicMock()
    offer_q1.filter.return_value.order_by.return_value.first.return_value = offer_b
    size_q2 = MagicMock()
    size_q2.filter.return_value.all.return_value = [size_o]
    offer_q2 = MagicMock()
    offer_q2.filter.return_value.order_by.return_value.first.return_value = offer_o

    db = MagicMock()
    db.query.side_effect = [size_q1, offer_q1, size_q2, offer_q2]

    stats = {"products": 0, "variations": 0, "errors": 0, "skipped": 0}
    upsert_calls = []

    def _upsert_var(*args, **kwargs):
        upsert_calls.append(kwargs)
        return {"id": kwargs.get("variation_id") or 999}

    with (
        patch.object(sync_mod, "_resolve_variable_parent_id", return_value=10),
        patch.object(sync_mod, "build_product_attributes", return_value=[]) as build_attrs,
        patch.object(sync_mod, "ensure_product_category", return_value=53),
        patch.object(sync_mod, "get_product_image_ids", return_value=[]),
        patch.object(sync_mod, "upload_product_image_from_url", return_value=None),
        patch.object(
            sync_mod,
            "create_or_update_variable_product",
            return_value={"id": 10},
        ) as upsert_product,
        patch.object(sync_mod, "upsert_variation", side_effect=_upsert_var),
        patch.object(sync_mod, "sync_offer_content"),
        patch.object(sync_mod, "maybe_push_woo_stock"),
        patch.object(
            sync_mod,
            "canonical_woo_product_name",
            return_value="Szelki dla psa Truelove Front Line",
        ),
    ):
        sync_mod._sync_one_family(
            db,
            client,
            [black, orange],
            refresh_content=False,
            stats=stats,
        )

    assert black.woo_product_id == 10
    assert orange.woo_product_id == 10
    assert stats["products"] == 1
    assert stats["variations"] == 2
    ba = build_attrs.call_args.kwargs
    assert set(ba["colors"]) == {"czarne", "pomarańczowe"}
    assert ba["size_options"] == ["L"]
    assert upsert_product.call_args.kwargs["name"] == "Szelki dla psa Truelove Front Line"
    colors_sent = {c["color"] for c in upsert_calls}
    assert colors_sent == {"czarne", "pomarańczowe"}
