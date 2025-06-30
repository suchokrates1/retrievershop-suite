from flask import Blueprint, render_template, request, redirect, url_for, flash
from .auth import login_required
from .env_info import ENV_INFO
from . import print_agent
from .db import get_session
from .models import Sale, Product, ShippingThreshold

bp = Blueprint("sales", __name__)


def calculate_shipping(amount: float) -> float:
    """Return shipping cost for given order value based on thresholds."""
    with get_session() as db:
        row = (
            db.query(ShippingThreshold)
            .filter(ShippingThreshold.min_order_value <= amount)
            .order_by(ShippingThreshold.min_order_value.desc())
            .first()
        )
        return row.shipping_cost if row else 0.0


@bp.route("/sales")
@login_required
def list_sales():
    """Display table of recorded sales with profit calculation."""
    with get_session() as db:
        rows = (
            db.query(Sale, Product)
            .join(Product, Sale.product_id == Product.id)
            .order_by(Sale.sale_date.desc())
            .all()
        )
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
            sales.append(
                {
                    "date": sale.sale_date,
                    "product": f"{product.name} ({product.color}) {sale.size}",
                    "purchase_cost": sale.purchase_cost,
                    "commission": sale.commission_fee,
                    "shipping": shipping,
                    "sale_price": sale.sale_price,
                    "profit": profit,
                }
            )
    return render_template("sales_list.html", sales=sales)


def _sales_keys(values):
    return [k for k in values.keys() if "SHIPPING" in k or "COMMISSION" in k]


@bp.route("/sales/settings", methods=["GET", "POST"])
@login_required
def sales_settings():
    from .app import load_settings, write_env

    values = load_settings()
    keys = _sales_keys(values)

    if request.method == "POST":
        for key in keys:
            values[key] = request.form.get(key, "")
        write_env(values)
        mins = request.form.getlist("threshold_min")
        costs = request.form.getlist("threshold_cost")
        with get_session() as db:
            db.query(ShippingThreshold).delete()
            for m, c in zip(mins, costs):
                if not m and not c:
                    continue
                db.add(
                    ShippingThreshold(
                        min_order_value=float(m or 0),
                        shipping_cost=float(c or 0),
                    )
                )
        print_agent.reload_config()
        flash("Zapisano ustawienia.")
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
    with get_session() as db:
        thresholds = (
            db.query(ShippingThreshold)
            .order_by(ShippingThreshold.min_order_value)
            .all()
        )
    return render_template(
        "sales_settings.html", settings=settings_list, thresholds=thresholds
    )
