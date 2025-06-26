from flask import Blueprint, render_template
from . import print_agent

from .auth import login_required
bp = Blueprint('history', __name__)


@bp.route('/history')
@login_required
def print_history():
    printed = print_agent.load_printed_orders()
    queue = print_agent.load_queue()
    return render_template('history.html', printed=printed, queue=queue)

