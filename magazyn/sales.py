from flask import Blueprint, render_template

from .auth import login_required
from .db import get_session
from .models import Sale, Product

bp = Blueprint('sales', __name__)


@bp.route('/sales')
@login_required
def list_sales():
    with get_session() as db:
        rows = (
            db.query(
                Sale.id,
                Sale.size,
                Sale.purchase_price,
                Sale.sale_price,
                Sale.shipping_cost,
                Sale.commission,
                Sale.platform,
                Sale.sale_date,
                Product.name,
                Product.color,
            )
            .join(Product, Sale.product_id == Product.id, isouter=True)
            .order_by(Sale.sale_date.desc())
            .all()
        )
    return render_template('sales.html', sales=rows)
