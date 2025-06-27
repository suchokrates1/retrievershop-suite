from flask import Blueprint, render_template, flash, redirect, url_for
from . import print_agent

from .auth import login_required
bp = Blueprint('history', __name__)


@bp.route('/history')
@login_required
def print_history():
    printed = print_agent.load_printed_orders()
    queue = print_agent.load_queue()
    return render_template('history.html', printed=printed, queue=queue)


@bp.route('/history/reprint/<order_id>', methods=['POST'])
@login_required
def reprint(order_id):
    success = print_agent.reprint_order(order_id)
    flash(
        'Etykieta ponownie wysłana do drukarki.' if success else 'Błąd ponownego wydruku.'
    )
    return redirect(url_for('history.print_history'))

