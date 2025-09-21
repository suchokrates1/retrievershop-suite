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
    """Display table of recorded sales with profit calculation."""
    with get_session() as db:
        rows = (
            db.query(Sale, Product)
            .outerjoin(Product, Sale.product_id == Product.id)
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
                    "purchase_cost": sale.purchase_cost,
                    "commission": sale.commission_fee,
                    "shipping": shipping,
                    "sale_price": sale.sale_price,
                    "profit": profit,
                }
            )
    return render_template("sales_list.html", sales=sales)


def _sales_keys(values):
    keywords = ("SHIPPING", "COMMISSION", "EMAIL", "SMTP")
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
                "Nie można zapisać ustawień sprzedaży, ponieważ baza konfiguracji jest w trybie tylko do odczytu."
            )
            return redirect(url_for("sales.sales_settings"))
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
    return render_template(
        "sales_settings.html", settings=settings_list
    )
