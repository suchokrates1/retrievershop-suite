from flask import Blueprint, render_template, request, redirect, url_for, flash
from .auth import login_required
from .config import settings
from .env_info import ENV_INFO
from . import print_agent

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


def _sales_keys(values):
    return [k for k in values.keys() if "SHIPPING" in k or "COMMISSION" in k]


@bp.route('/sales/settings', methods=['GET', 'POST'])
@login_required
def sales_settings():
    from .app import load_settings, write_env

    values = load_settings()
    keys = _sales_keys(values)

    if request.method == 'POST':
        for key in keys:
            values[key] = request.form.get(key, "")
        write_env(values)
        print_agent.reload_config()
        flash("Zapisano ustawienia.")
        return redirect(url_for('sales.sales_settings'))

    settings_list = []
    for key in keys:
        label, desc = ENV_INFO.get(key, (key, None))
        settings_list.append({
            'key': key,
            'label': label,
            'desc': desc,
            'value': values[key],
        })
    return render_template('sales_settings.html', settings=settings_list)
