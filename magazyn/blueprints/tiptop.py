"""HTTP routes for TipTop reorder (osobny blueprint — poza budżetem products.py)."""

from __future__ import annotations

import logging

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for

from magazyn.auth import login_required
from magazyn.db import get_session

bp = Blueprint("tiptop", __name__)
logger = logging.getLogger(__name__)


@bp.route("/tiptop/reorder", methods=["GET", "POST"])
@login_required
def reorder():
    """Lista braków magazynowych do zamówienia na TipTop24."""
    from magazyn.models.tiptop import TipTopProduct
    from magazyn.services.tiptop_reorder import (
        TIPTOP_ADD_URL,
        TIPTOP_BASKET_URL,
        _tiptop_reorder_threshold,
        add_exclusion,
        build_browser_fill_items,
        build_cart_payload,
        build_reorder_candidates,
        list_exclusions_enriched,
        remove_exclusion,
    )
    from magazyn.settings_store import settings_store

    if request.method == "POST":
        action = (request.form.get("action") or "").strip()

        def _tiptop_redirect():
            if request.form.get("open_settings") == "1":
                return redirect(url_for("tiptop.reorder", settings=1))
            return redirect(url_for("tiptop.reorder"))

        if action == "exclude_size":
            ps_id = request.form.get("product_size_id", type=int)
            if ps_id:
                with get_session() as db:
                    add_exclusion(
                        db,
                        product_size_id=ps_id,
                        reason=request.form.get("reason") or "Wykluczone z reorder TipTop",
                    )
                flash("Wykluczono wariant z listy zamówień TipTop", "success")
            return _tiptop_redirect()

        if action == "exclude_product":
            product_id = request.form.get("product_id", type=int)
            if product_id:
                with get_session() as db:
                    add_exclusion(
                        db,
                        product_id=product_id,
                        reason=request.form.get("reason") or "Wykluczono cały produkt",
                    )
                flash("Wykluczono produkt z listy zamówień TipTop", "success")
            return _tiptop_redirect()

        if action == "remove_exclusion":
            excl_id = request.form.get("exclusion_id", type=int)
            if excl_id:
                with get_session() as db:
                    remove_exclusion(db, excl_id)
                flash("Usunięto wykluczenie TipTop", "success")
            return redirect(url_for("tiptop.reorder", settings=1))

        if action == "save_settings":
            raw = (request.form.get("tiptop_reorder_threshold") or "").strip()
            try:
                thr = max(0, int(raw))
            except (TypeError, ValueError):
                flash("Próg braków musi być liczbą całkowitą ≥ 0", "error")
                return redirect(url_for("tiptop.reorder", settings=1))
            settings_store.update({"TIPTOP_REORDER_THRESHOLD": str(thr)})
            flash(f"Zapisano próg braków TipTop: ≤ {thr}", "success")
            return redirect(url_for("tiptop.reorder", settings=1))

        if action == "create_cart":
            selected = request.form.getlist("selected")
            selections = []
            for ps_id_raw in selected:
                try:
                    ps_id = int(ps_id_raw)
                except (TypeError, ValueError):
                    continue
                qty_raw = request.form.get(f"qty_{ps_id}", "0")
                try:
                    qty = int(qty_raw)
                except (TypeError, ValueError):
                    qty = 0
                selections.append({"product_size_id": ps_id, "quantity": qty})

            with get_session() as db:
                items = build_cart_payload(db, selections)
            if not items:
                flash(
                    "Brak zaznaczonych pozycji z mapowaniem TipTop. "
                    "Odśwież katalog lub sprawdź linki.",
                    "error",
                )
                return redirect(url_for("tiptop.reorder"))

            return render_template(
                "tiptop_cart_fill.html",
                items=items,
                fill_items=build_browser_fill_items(items),
                add_url=TIPTOP_ADD_URL,
                basket_url=TIPTOP_BASKET_URL,
            )

    threshold = _tiptop_reorder_threshold()
    with get_session() as db:
        lines = build_reorder_candidates(db)
        exclusions = list_exclusions_enriched(db)
        catalog_count = db.query(TipTopProduct).count()

    return render_template(
        "tiptop_reorder.html",
        lines=lines,
        exclusions=exclusions,
        catalog_count=catalog_count,
        threshold=threshold,
        open_settings=request.args.get("settings") == "1",
    )


@bp.route("/tiptop/reorder/search-products")
@login_required
def search_products():
    from magazyn.services.tiptop_reorder import search_products_for_exclusion

    q = request.args.get("q", "")
    with get_session() as db:
        return jsonify(search_products_for_exclusion(db, q))


@bp.route("/tiptop/reorder/refresh-catalog", methods=["POST"])
@login_required
def refresh_catalog():
    from magazyn.services.tiptop_catalog import refresh_truelove_catalog

    max_pages = request.form.get("max_pages", type=int) or 5
    max_products = request.form.get("max_products", type=int) or 80
    try:
        with get_session() as db:
            result = refresh_truelove_catalog(
                db, max_pages=max_pages, max_products=max_products
            )
        flash(
            f"Katalog TipTop: produkty {result.products_upserted}, "
            f"warianty {result.variants_upserted}, "
            f"linki +{result.links_created}/~{result.links_updated}, "
            f"błędy {len(result.errors)}",
            "success" if result.products_upserted else "warning",
        )
        for err in result.errors[:5]:
            flash(err, "error")
    except Exception as exc:
        logger.exception("TipTop catalog refresh failed")
        flash(f"Odświeżanie katalogu TipTop nie powiodło się: {exc}", "error")
    return redirect(url_for("tiptop.reorder"))


@bp.route("/tiptop/reorder/cart-payload.json", methods=["POST"])
@login_required
def cart_payload():
    from magazyn.services.tiptop_reorder import (
        TIPTOP_ADD_URL,
        TIPTOP_BASKET_URL,
        build_browser_fill_items,
        build_cart_payload,
    )

    data = request.get_json(silent=True) or {}
    selections = data.get("selections") or []
    with get_session() as db:
        items = build_cart_payload(db, selections)
    return jsonify(
        {
            "items": items,
            "fill_items": build_browser_fill_items(items),
            "add_url": TIPTOP_ADD_URL,
            "basket_url": TIPTOP_BASKET_URL,
        }
    )
