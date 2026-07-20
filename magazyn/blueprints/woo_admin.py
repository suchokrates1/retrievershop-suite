"""Reczne akcje sync Woo (UI zamowien)."""

from flask import Blueprint, flash, redirect, url_for

from ..auth import login_required

bp = Blueprint("woo_admin", __name__)


@bp.route("/orders/sync-woo", methods=["POST"])
@login_required
def sync_woo_orders_route():
    """Reczna synchronizacja zamowien WooCommerce."""
    from ..services.woo_order_sync import sync_woo_orders

    stats = sync_woo_orders()
    flash(
        f"Woo sync: fetched={stats.get('fetched')} imported={stats.get('imported')} "
        f"skipped={stats.get('skipped')} errors={stats.get('errors')}",
        "success" if not stats.get("errors") else "warning",
    )
    return redirect(url_for("orders.orders_list"))


@bp.route("/orders/sync-woo-catalog", methods=["POST"])
@login_required
def sync_woo_catalog_route():
    """Reczna synchronizacja katalogu do WooCommerce."""
    from ..services.allegro_offer_content import sync_linked_offers_content
    from ..services.woo_catalog_sync import sync_catalog_to_woo

    content = sync_linked_offers_content(limit=60)
    catalog = sync_catalog_to_woo(limit=200, refresh_content=False)
    flash(
        f"Tresc Allegro: {content}; Katalog Woo: {catalog}",
        "success" if not catalog.get("errors") else "warning",
    )
    return redirect(url_for("orders.orders_list"))


@bp.route("/orders/reconcile-woo-stock", methods=["POST"])
@login_required
def reconcile_woo_stock_route():
    """Reconcile stanow Woo z magazynem + dedupe SKU."""
    from ..services.woo_stock_reconcile import reconcile_woo_stock

    dry_run = False
    stats = reconcile_woo_stock(dry_run=dry_run)
    flash(
        f"Woo reconcile: updated={stats.get('updated')} deduped={stats.get('deduped')} "
        f"orphaned={stats.get('orphaned')} remapped={stats.get('remapped')} "
        f"errors={stats.get('errors')}",
        "success" if not stats.get("errors") else "warning",
    )
    return redirect(url_for("orders.orders_list"))
