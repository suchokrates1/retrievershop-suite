"""Endpointy zarzadzania kosztami stalymi."""

from __future__ import annotations

from flask import Blueprint, flash, redirect, url_for

from ..auth import login_required
from ..forms import FixedCostForm
from ..services.fixed_costs import (
    FixedCostActionResult,
    add_fixed_cost as add_fixed_cost_record,
    delete_fixed_cost as delete_fixed_cost_record,
    edit_fixed_cost as edit_fixed_cost_record,
    toggle_fixed_cost as toggle_fixed_cost_record,
)

bp = Blueprint("fixed_costs", __name__)


def _invalid_fixed_cost_form_result(form: FixedCostForm) -> FixedCostActionResult:
    return FixedCostActionResult("Nieprawidlowe dane kosztu stalego.", "error")


@bp.route("/fixed-costs/add", methods=["POST"])
@login_required
def add_fixed_cost():
    """Dodaj nowy koszt staly."""
    form = FixedCostForm()
    if form.validate_on_submit():
        result = add_fixed_cost_record(
            form.name.data,
            str(form.amount.data),
            form.description.data or "",
        )
    else:
        result = _invalid_fixed_cost_form_result(form)
    flash(result.message, result.category)
    return redirect(url_for("settings_page"))


@bp.route("/fixed-costs/<int:cost_id>/toggle", methods=["POST"])
@login_required
def toggle_fixed_cost(cost_id):
    """Wlacz/wylacz koszt staly."""
    result = toggle_fixed_cost_record(cost_id)
    flash(result.message, result.category)
    return redirect(url_for("settings_page"))


@bp.route("/fixed-costs/<int:cost_id>/delete", methods=["POST"])
@login_required
def delete_fixed_cost(cost_id):
    """Usun koszt staly."""
    result = delete_fixed_cost_record(cost_id)
    flash(result.message, result.category)
    return redirect(url_for("settings_page"))


@bp.route("/fixed-costs/<int:cost_id>/edit", methods=["POST"])
@login_required
def edit_fixed_cost(cost_id):
    """Edytuj koszt staly."""
    form = FixedCostForm()
    if form.validate_on_submit():
        result = edit_fixed_cost_record(
            cost_id,
            form.name.data,
            str(form.amount.data),
            form.description.data or "",
        )
    else:
        result = _invalid_fixed_cost_form_result(form)
    flash(result.message, result.category)
    return redirect(url_for("settings_page"))