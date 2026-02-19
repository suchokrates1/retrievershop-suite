from flask import (
    Blueprint,
    current_app,
    render_template,
    request,
    redirect,
    url_for,
    flash,
)
from .auth import login_required
from .env_info import ENV_INFO
from . import print_agent
from .db import get_session
from .settings_store import SettingsPersistenceError, settings_store
from .models import Sale, Product, ShippingThreshold
from sqlalchemy import or_
from decimal import Decimal

bp = Blueprint("sales", __name__)


def calculate_shipping(amount: Decimal) -> Decimal:
    """Return shipping cost for given order value based on thresholds."""
    with get_session() as db:
        row = (
            db.query(ShippingThreshold)
            .filter(ShippingThreshold.min_order_value <= float(amount))
            .order_by(ShippingThreshold.min_order_value.desc())
            .first()
        )
        return row.shipping_cost if row else Decimal("0.00")


@bp.route("/sales")
@login_required
def list_sales():
    """Display table of recorded sales with profit calculation, pagination and search."""
    search = request.args.get("search", "").strip()
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 25, type=int)
    if per_page not in [25, 50, 100]:
        per_page = 25
    
    with get_session() as db:
        query = db.query(Sale, Product).outerjoin(Product, Sale.product_id == Product.id)
        
        if search:
            search_pattern = f"%{search}%"
            query = query.filter(
                db.query(Sale).filter(
                    Sale.id == Sale.id  # placeholder
                ).correlate(Sale).exists()
            )
            # Filtruj po nazwie produktu
            query = (
                db.query(Sale, Product)
                .outerjoin(Product, Sale.product_id == Product.id)
                .filter(
                    or_(
                        Product.category.ilike(search_pattern),
                        Product.series.ilike(search_pattern),
                        Product.color.ilike(search_pattern),
                        Product.brand.ilike(search_pattern),
                        Sale.size.ilike(search_pattern),
                    )
                )
            )
        
        query = query.order_by(Sale.sale_date.desc())
        total = query.count()
        rows = query.offset((page - 1) * per_page).limit(per_page).all()
        
        # Oblicz sumy dla calosciowego podsumowania (bez paginacji)
        all_rows = (
            db.query(Sale, Product)
            .outerjoin(Product, Sale.product_id == Product.id)
        )
        if search:
            search_pattern = f"%{search}%"
            all_rows = all_rows.filter(
                or_(
                    Product.category.ilike(search_pattern),
                    Product.series.ilike(search_pattern),
                    Product.color.ilike(search_pattern),
                    Product.brand.ilike(search_pattern),
                    Sale.size.ilike(search_pattern),
                )
            )
        
        from sqlalchemy import func as sqfunc
        totals = db.query(
            sqfunc.sum(Sale.sale_price),
            sqfunc.sum(Sale.purchase_cost),
            sqfunc.sum(Sale.commission_fee),
        ).select_from(Sale)
        if search:
            totals = totals.outerjoin(Product, Sale.product_id == Product.id).filter(
                or_(
                    Product.category.ilike(search_pattern),
                    Product.series.ilike(search_pattern),
                    Product.color.ilike(search_pattern),
                    Product.brand.ilike(search_pattern),
                    Sale.size.ilike(search_pattern),
                )
            )
        totals_row = totals.first()
        total_sale_price = float(totals_row[0] or 0)
        total_purchase_cost = float(totals_row[1] or 0)
        total_commission = float(totals_row[2] or 0)
        
        sales = []
        for sale, product in rows:
            shipping = sale.shipping_cost or calculate_shipping(
                sale.sale_price
            )
            profit = (
                sale.sale_price
                - sale.purchase_cost
                - shipping
                - sale.commission_fee
            )
            name = "unknown" if not product else product.name
            color = "" if not product else product.color
            descr = (
                f"{name} ({color}) {sale.size}"
                if color
                else f"{name} {sale.size}"
            )
            sales.append(
                {
                    "date": sale.sale_date,
                    "product": descr,
                    "purchase_cost": float(sale.purchase_cost),
                    "commission": float(sale.commission_fee),
                    "shipping": float(shipping),
                    "sale_price": float(sale.sale_price),
                    "profit": float(profit),
                }
            )
    
    total_pages = max(1, (total + per_page - 1) // per_page)
    total_profit = total_sale_price - total_purchase_cost - total_commission
    
    return render_template(
        "sales_list.html",
        sales=sales,
        search=search,
        page=page,
        per_page=per_page,
        total=total,
        total_pages=total_pages,
        has_prev=page > 1,
        has_next=page < total_pages,
        summary={
            "sale_price": total_sale_price,
            "purchase_cost": total_purchase_cost,
            "commission": total_commission,
            "profit": total_profit,
        },
    )


def _sales_keys(values):
    keywords = ("SHIPPING", "COMMISSION", "EMAIL", "SMTP", "PRICE_MAX_DISCOUNT")
    return [
        k for k in values.keys() if any(word in k for word in keywords)
    ]


@bp.route("/sales/settings", methods=["GET", "POST"])
@login_required
def sales_settings():
    from .app import load_settings

    values = load_settings(include_hidden=True)
    keys = _sales_keys(values)

    if request.method == "POST":
        updates = {key: request.form.get(key, values.get(key, "")) for key in keys}
        try:
            settings_store.update(updates)
        except SettingsPersistenceError as exc:
            current_app.logger.error(
                "Failed to persist sales settings", exc_info=exc
            )
            flash(
                "Nie można zapisać ustawień sprzedaży, ponieważ baza konfiguracji jest w trybie tylko do odczytu.",
                "error",
            )
            return redirect(url_for("sales.sales_settings"))
        print_agent.reload_config()
        flash("Zapisano ustawienia.", "success")
        return redirect(url_for("sales.sales_settings"))

    settings_list = []
    for key in keys:
        label, desc = ENV_INFO.get(key, (key, None))
        settings_list.append(
            {
                "key": key,
                "label": label,
                "desc": desc,
                "value": values[key],
            }
        )
    return render_template(
        "sales_settings.html", settings=settings_list
    )
