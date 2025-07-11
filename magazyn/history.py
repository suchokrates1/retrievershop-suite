from .auth import login_required
from flask import Blueprint, render_template, redirect, url_for, flash
from . import print_agent

logger = print_agent.logger

bp = Blueprint("history", __name__)


@bp.route("/history")
@login_required
def print_history():
    printed = print_agent.load_printed_orders()
    queue = print_agent.load_queue()
    return render_template("history.html", printed=printed, queue=queue)


@bp.route("/history/reprint/<order_id>", methods=["POST"])
@login_required
def reprint_label(order_id):
    """Reprint shipping labels for the given order."""
    try:
        all_items = print_agent.load_queue()
        queue = [
            q
            for q in all_items
            if str(q.get("order_id")) == str(order_id)
        ]
        printed_data = None
        try:
            for it in print_agent.load_printed_orders():
                if str(it.get("order_id")) == str(order_id):
                    printed_data = it.get("last_order_data")
                    break
        except Exception:
            printed_data = None

        if queue:
            remaining = [
                q
                for q in all_items
                if str(q.get("order_id")) != str(order_id)
            ]
            for item in queue:
                print_agent.print_label(
                    item.get("label_data"),
                    item.get("ext", "pdf"),
                    order_id,
                )
            print_agent.save_queue(remaining)
            print_agent.mark_as_printed(
                order_id,
                queue[0].get("last_order_data", printed_data),
            )
        else:
            packages = print_agent.get_order_packages(order_id)
            for p in packages:
                pid = p.get("package_id")
                code = p.get("courier_code")
                if not pid or not code:
                    continue
                label_data, ext = print_agent.get_label(code, pid)
                if label_data:
                    print_agent.print_label(label_data, ext, order_id)
            print_agent.mark_as_printed(order_id, printed_data)
        flash("Etykieta została ponownie wysłana do drukarki.")
    except Exception as exc:
        logger.exception("Reprint failed for %s", order_id)
        flash(f"Błąd ponownego drukowania: {exc}")
    return redirect(url_for(".print_history"))
