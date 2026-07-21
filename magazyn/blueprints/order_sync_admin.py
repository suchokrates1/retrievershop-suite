"""Reczne synci Allegro + API wyszukiwania produktow (UI zamowien)."""

from __future__ import annotations

from flask import Blueprint, current_app, flash, jsonify, redirect, request, url_for

from ..auth import login_required
from ..db import get_session
from ..services.order_allegro_sync import sync_orders_from_allegro_api
from ..services.order_status import add_order_status
from ..services.order_sync import sync_order_from_data

bp = Blueprint("order_sync_admin", __name__)


@bp.route("/orders/api/products/search")
@login_required
def api_product_search():
    """API wyszukiwania produktow do formularza recznego zamowienia."""
    q = request.args.get("q", "").strip()
    if len(q) < 2:
        return jsonify([])

    with get_session() as db:
        from ..models.products import Product, ProductSize

        query = (
            db.query(ProductSize)
            .join(Product, Product.id == ProductSize.product_id)
            .filter(ProductSize.quantity > 0)
        )

        # Szukaj po barcode, nazwie, kolorze, serii
        like_q = f"%{q}%"
        query = query.filter(
            (ProductSize.barcode.ilike(like_q))
            | (Product._name.ilike(like_q))
            | (Product.color.ilike(like_q))
            | (Product.series.ilike(like_q))
            | (Product.category.ilike(like_q))
            | (Product.brand.ilike(like_q))
        )

        results = []
        for ps in query.limit(20).all():
            product = ps.product
            label = (
                f"{product.name} | {product.color or '-'} | {ps.size} | "
                f"EAN: {ps.barcode or '-'} | Stan: {ps.quantity}"
            )
            results.append(
                {
                    "name": f"{product.name} - {product.color or ''} - {ps.size}".strip(" -"),
                    "ean": ps.barcode or "",
                    "size": ps.size,
                    "stock": ps.quantity,
                    "label": label,
                }
            )

    return jsonify(results)


@bp.route("/orders/sync-all", methods=["POST"])
@login_required
def sync_all_orders():
    """Reczne uruchomienie syncu zamowien z Allegro Events API."""
    try:
        from ..order_sync_scheduler import _sync_from_allegro_events

        current_app.logger.info("Reczny sync zamowien z Allegro Events API")
        ev_stats = _sync_from_allegro_events(current_app._get_current_object())

        synced = ev_stats.get("orders_synced", 0)
        cancelled = ev_stats.get("orders_cancelled", 0)
        current_app.logger.info(
            "Reczny sync zakonczony: %d zsynchronizowanych, %d anulowanych",
            synced,
            cancelled,
        )
        flash(
            f"Zsynchronizowano {synced} zamowien z Allegro (anulowane: {cancelled})",
            "success",
        )
    except Exception as exc:
        current_app.logger.error("Blad recznego syncu zamowien: %s", exc)
        flash(f"Blad synchronizacji: {exc}", "error")

    return redirect(url_for("orders.orders_list"))


@bp.route("/orders/sync-allegro", methods=["POST"])
@login_required
def sync_allegro_orders():
    """
    Synchronizacja zamowien bezposrednio z Allegro REST API.

    Allegro zwraca zamowienia z ostatnich 12 miesiecy (max).
    Paginacja: offset/limit, max offset+limit = 10000.
    Uzywa GET /order/checkout-forms.
    """
    try:
        current_app.logger.info("Rozpoczynam sync zamowien z Allegro API...")
        with get_session() as db:
            result = sync_orders_from_allegro_api(
                db,
                sync_order_from_data=sync_order_from_data,
                add_order_status=add_order_status,
                logger=current_app.logger,
            )
        current_app.logger.info(result.message)
        flash(result.message, "success")

    except Exception as exc:
        current_app.logger.error("Blad sync zamowien z Allegro API: %s", exc)
        flash(f"Blad synchronizacji z Allegro: {exc}", "error")

    return redirect(url_for("orders.orders_list"))
