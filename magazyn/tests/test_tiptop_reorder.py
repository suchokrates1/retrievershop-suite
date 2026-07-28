"""Tests for TipTop catalog scrape, matching, reorder and cart filler."""

from __future__ import annotations

import json

import pytest

from magazyn.db import get_session
from magazyn.models.products import Product, ProductSize
from magazyn.models.tiptop import TipTopProduct, TipTopProductLink, TipTopVariant
from magazyn.services.tiptop_catalog import (
    expand_variants,
    extract_product_links_from_listing,
    parse_product_page,
    score_variant_match,
    sync_catalog_from_urls,
    upsert_parsed_product,
)
from magazyn.services.tiptop_reorder import (
    add_exclusion,
    build_browser_fill_items,
    build_cart_payload,
    build_reorder_candidates,
    cart_item_to_add_fields,
    list_exclusions_enriched,
)
from magazyn.tests.fixtures.tiptop_product_page import (
    TIPTOP_ACTIVE_COLLAR_HTML,
)


def test_parse_product_page_extracts_stock_and_options():
    parsed = parse_product_page(
        TIPTOP_ACTIVE_COLLAR_HTML,
        "https://tiptop24.pl/dla-psa/obroza-dla-psa-truelove-active",
    )
    assert parsed.tiptop_product_id == 214
    assert "Active" in parsed.name
    assert parsed.size_option_id == 8
    assert parsed.color_option_id == 9
    assert parsed.price == 59.0
    sizes = {v for o in parsed.options if o.option_id == 8 for _, v in o.values}
    colors = {v for o in parsed.options if o.option_id == 9 for _, v in o.values}
    assert "L" in sizes
    assert "czarny" in colors


def test_expand_variants_cartesian():
    parsed = parse_product_page(
        TIPTOP_ACTIVE_COLLAR_HTML,
        "https://tiptop24.pl/dla-psa/obroza-dla-psa-truelove-active",
    )
    variants = expand_variants(parsed)
    # 5 sizes × 3 colors
    assert len(variants) == 15
    black_l = next(
        v
        for v in variants
        if v["size_label"] == "L" and v["color_label"] == "czarny"
    )
    assert black_l["option_map"] == {"8": 51, "9": 60}


def test_extract_product_links_from_listing():
    html = """
    <a href="/dla-psa/szelki-guard-dla-psa-truelove-front-line-czerwone">ok</a>
    <a href="/dla-psa/szelki-dla-psa/szelki-dla-psa-modele/szelki-truelove-front-line">modele</a>
    <a href="/dla-psa/szelki-dla-psa">cat</a>
    <a href="/basket">koszyk</a>
    """
    urls = extract_product_links_from_listing(html)
    assert any("front-line-czerwone" in u for u in urls)
    assert all("/modele/" not in u for u in urls)
    assert all(u.rstrip("/").endswith("szelki-dla-psa") is False for u in urls)
    assert all("/basket" not in u for u in urls)


def test_score_variant_match_active_collar(app):
    product = Product(category="Obroża", brand="Truelove", series="Active", color="czarny")
    size = ProductSize(size="L", quantity=0)
    score = score_variant_match(
        tip_name="Obroża dla psa Truelove Active",
        tip_size="L",
        tip_color="czarny",
        product=product,
        size=size,
    )
    assert score is not None and score >= 0.45

    bad = score_variant_match(
        tip_name="Obroża dla psa Truelove Active",
        tip_size="S",
        tip_color="czarny",
        product=product,
        size=size,
    )
    assert bad is None


def test_upsert_and_auto_link_creates_reorder_candidates(app, monkeypatch):
    monkeypatch.setattr(
        "magazyn.services.tiptop_reorder.settings.TIPTOP_REORDER_THRESHOLD", "5"
    )

    with get_session() as db:
        product = Product(
            category="Obroża", brand="Truelove", series="Active", color="czarny"
        )
        db.add(product)
        db.flush()
        ps = ProductSize(product_id=product.id, size="L", quantity=1)
        db.add(ps)
        db.flush()

        parsed = parse_product_page(
            TIPTOP_ACTIVE_COLLAR_HTML,
            "https://tiptop24.pl/dla-psa/obroza-dla-psa-truelove-active",
        )
        upsert_parsed_product(db, parsed)
        from magazyn.services.tiptop_catalog import auto_link_variants

        created, _ = auto_link_variants(db, only_tiptop_product_id=214)
        assert created >= 1

        lines = build_reorder_candidates(db, threshold=5, target=5)
        assert len(lines) == 1
        assert lines[0].product_size_id == ps.id
        assert lines[0].suggested_qty == 4
        assert lines[0].stock_id == 214
        assert lines[0].options.get("8") == 51
        assert lines[0].options.get("9") == 60


def test_exclusion_hides_line(app, monkeypatch):
    monkeypatch.setattr(
        "magazyn.services.tiptop_reorder.settings.TIPTOP_REORDER_THRESHOLD", "5"
    )

    with get_session() as db:
        product = Product(
            category="Obroża", brand="Truelove", series="Active", color="czarny"
        )
        db.add(product)
        db.flush()
        ps = ProductSize(product_id=product.id, size="L", quantity=0)
        db.add(ps)
        db.flush()

        tip = TipTopProduct(
            tiptop_product_id=214,
            url="https://tiptop24.pl/dla-psa/obroza",
            name="Obroża dla psa Truelove Active",
            producer="Truelove",
        )
        db.add(tip)
        db.flush()
        variant = TipTopVariant(
            tiptop_product_id=214,
            option_map=json.dumps({"8": 51, "9": 60}),
            size_label="L",
            color_label="czarny",
        )
        db.add(variant)
        db.flush()
        db.add(
            TipTopProductLink(
                product_size_id=ps.id,
                tiptop_variant_id=variant.id,
                match_type="manual",
                match_confidence=1.0,
            )
        )
        db.flush()

        assert len(build_reorder_candidates(db)) == 1
        add_exclusion(db, product_size_id=ps.id, reason="test")
        assert build_reorder_candidates(db) == []


def test_build_filler_script_and_cart_payload(app):
    with get_session() as db:
        product = Product(
            category="Obroża", brand="Truelove", series="Active", color="czarny"
        )
        db.add(product)
        db.flush()
        ps = ProductSize(product_id=product.id, size="L", quantity=0)
        db.add(ps)
        db.flush()
        tip = TipTopProduct(
            tiptop_product_id=214,
            url="https://tiptop24.pl/x",
            name="Obroża Active",
        )
        db.add(tip)
        db.flush()
        variant = TipTopVariant(
            tiptop_product_id=214,
            option_map='{"8": 51, "9": 60}',
            size_label="L",
            color_label="czarny",
        )
        db.add(variant)
        db.flush()
        db.add(
            TipTopProductLink(
                product_size_id=ps.id,
                tiptop_variant_id=variant.id,
                match_type="manual",
            )
        )
        db.flush()

        items = build_cart_payload(
            db, [{"product_size_id": ps.id, "quantity": 3}]
        )
        assert len(items) == 1
        assert items[0]["stock_id"] == 214
        assert items[0]["quantity"] == 3
        assert items[0]["options"] == {"8": 51, "9": 60}

        from magazyn.services.tiptop_reorder import (
            build_browser_fill_items,
            cart_item_to_add_fields,
        )

        fields = cart_item_to_add_fields(items[0])
        assert fields["stock_id"] == "214"
        assert fields["quantity"] == "3"
        assert fields["option_8"] == "51"
        assert fields["option_9"] == "60"
        fill = build_browser_fill_items(items)
        assert len(fill) == 1
        assert fill[0]["fields"]["stock_id"] == "214"


def test_tiptop_reorder_page_requires_login(client):
    resp = client.get("/tiptop/reorder")
    assert resp.status_code in (302, 401)


def test_sync_catalog_from_urls_uses_fetch(app, monkeypatch):
    calls = []

    def fake_fetch(url, session=None, timeout=30):
        calls.append(url)
        return TIPTOP_ACTIVE_COLLAR_HTML

    monkeypatch.setattr(
        "magazyn.services.tiptop_catalog.fetch_html", fake_fetch
    )
    with get_session() as db:
        result = sync_catalog_from_urls(
            db,
            ["https://tiptop24.pl/dla-psa/obroza-dla-psa-truelove-active"],
            auto_link=False,
        )
        assert result.products_upserted == 1
        assert result.variants_upserted == 15
        assert db.query(TipTopProduct).count() == 1
        assert db.query(TipTopVariant).count() == 15
    assert calls


def test_tiptop_threshold_setting_controls_candidates(app, monkeypatch):
    monkeypatch.setattr(
        "magazyn.services.tiptop_reorder.settings.TIPTOP_REORDER_THRESHOLD", "1"
    )
    with get_session() as db:
        product = Product(
            category="Obroża", brand="Truelove", series="Active", color="czarny"
        )
        db.add(product)
        db.flush()
        ps_low = ProductSize(product_id=product.id, size="L", quantity=1)
        ps_ok = ProductSize(product_id=product.id, size="M", quantity=5)
        db.add_all([ps_low, ps_ok])
        db.flush()
        tip = TipTopProduct(
            tiptop_product_id=214,
            url="https://tiptop24.pl/x",
            name="Obroża Active",
        )
        db.add(tip)
        db.flush()
        for ps, size_label, opt in ((ps_low, "L", 51), (ps_ok, "M", 50)):
            v = TipTopVariant(
                tiptop_product_id=214,
                option_map=json.dumps({"8": opt, "9": 60}),
                size_label=size_label,
                color_label="czarny",
            )
            db.add(v)
            db.flush()
            db.add(
                TipTopProductLink(
                    product_size_id=ps.id,
                    tiptop_variant_id=v.id,
                    match_type="manual",
                )
            )
        db.flush()
        lines = build_reorder_candidates(db)
        assert [l.product_size_id for l in lines] == [ps_low.id]
        assert lines[0].suggested_qty == 1
        lines2 = build_reorder_candidates(db, threshold=1, target=2)
        assert len(lines2) == 1
        assert lines2[0].product_size_id == ps_low.id
        assert lines2[0].suggested_qty == 1

def test_exclusions_enriched_labels(app):
    from magazyn.services.tiptop_reorder import add_exclusion, list_exclusions_enriched

    with get_session() as db:
        product = Product(
            category="Obroża", brand="Truelove", series="Active", color="czarny"
        )
        db.add(product)
        db.flush()
        add_exclusion(db, product_id=product.id, reason="test")
        views = list_exclusions_enriched(db)
        assert len(views) == 1
        assert "Active" in views[0].label
        assert views[0].scope == "product"
