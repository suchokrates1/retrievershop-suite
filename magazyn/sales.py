from flask import Blueprint, render_template, request
from .auth import login_required
from .config import settings

bp = Blueprint('sales', __name__)

PLATFORMS = {
    'allegro': {
        'shipping': settings.DEFAULT_SHIPPING_ALLEGRO,
        'commission': settings.COMMISSION_ALLEGRO,
    },
    'vinted': {
        'shipping': settings.DEFAULT_SHIPPING_VINTED,
        'commission': settings.COMMISSION_VINTED,
    },
}


@bp.route('/sales')
@login_required
def list_sales():
    """Placeholder page listing sales."""
    return 'Sales list'

@bp.route('/sales/profit', methods=['GET', 'POST'])
@login_required
def sales_page():
    platform = request.form.get('platform', 'allegro')
    config = PLATFORMS.get(platform, {'shipping': 0.0, 'commission': 0.0})
    price = request.form.get('price', '')
    shipping = float(request.form.get('shipping', config['shipping'] or 0))
    commission = float(request.form.get('commission', config['commission'] or 0))
    result = None
    if request.method == 'POST':
        try:
            price_val = float(price)
            result = round(price_val - shipping - price_val * commission / 100, 2)
        except ValueError:
            result = None
    return render_template(
        'sales.html',
        platforms=PLATFORMS.keys(),
        platform=platform,
        price=price,
        shipping=shipping,
        commission=commission,
        result=result,
    )
