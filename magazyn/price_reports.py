"""
Blueprint i logika dla raportow cenowych.

Funkcjonalnosci:
- Wyswietlanie raportow cenowych
- Filtrowanie (tylko gdzie nie jestesmy najtansi)
- Historia raportow
- Sugestie cen
- Wykluczanie sprzedawcow
- Zmiana cen na Allegro
"""

from flask import (
    Blueprint,
    render_template,
    request,
    jsonify,
    flash,
    redirect,
    url_for,
)
import logging

from .auth import login_required
from .db import get_session
from .models.price_reports import PriceReportItem
from .settings_store import settings_store
from .domain.exceptions import EntityNotFoundError
from .domain.price_report_profit import calculate_report_item_profit
from .services import price_report_admin
from .services.price_report_mutation import change_report_item_price, recheck_report_item
from .services.price_report_view import (
    build_report_detail_context,
    build_reports_list_context,
    current_report_status_payload,
)

logger = logging.getLogger(__name__)

bp = Blueprint("price_reports", __name__, url_prefix="/price-reports")


def get_max_discount_percent() -> float:
    """Pobiera maksymalny procent znizki z ustawien."""
    return price_report_admin.get_max_discount_percent()


@bp.route("/")
@login_required
def reports_list():
    """Lista wszystkich raportow cenowych."""
    return render_template("price_reports/reports_list.html", **build_reports_list_context())


@bp.route("/<int:report_id>")
@login_required
def report_detail(report_id: int):
    """Szczegoly raportu cenowego."""
    filter_mode = request.args.get("filter", "all")  # all, not_cheapest, cheapest, inna_aukcja_ok, errors
    try:
        context = build_report_detail_context(report_id, filter_mode)
    except EntityNotFoundError:
        flash("Raport nie istnieje", "error")
        return redirect(url_for("price_reports.reports_list"))

    return render_template("price_reports/report_detail.html", **context)


@bp.route("/current-status")
@login_required
def current_status():
    """Zwraca status biezacego raportu (dla AJAX)."""
    return jsonify(current_report_status_payload())


@bp.route("/start-manual", methods=["POST"])
@login_required
def start_manual_report():
    """Reczne uruchomienie raportu cenowego."""
    try:
        result = price_report_admin.start_manual_report()
        flash(result.message, result.category)
    except Exception as exc:
        logger.exception("Blad uruchamiania raportu")
        flash(f"Blad: {exc}", "error")
    
    return redirect(url_for("price_reports.reports_list"))


@bp.route("/resume/<int:report_id>", methods=["POST"])
@login_required
def resume_report(report_id):
    """Wznawia przetwarzanie przerwanego raportu."""
    try:
        result = price_report_admin.resume_report(report_id)
        flash(result.message, result.category)
    except Exception as exc:
        logger.exception("Blad wznawiania raportu")
        flash(f"Blad: {exc}", "error")
    
    return redirect(url_for("price_reports.reports_list"))


@bp.route("/restart/<int:report_id>", methods=["POST"])
@login_required
def restart_report(report_id):
    """Restartuje raport - sprawdza niesprawdzone oferty i te z bledami.
    
    - Usuwa wpisy z bledami (zeby mogly byc sprawdzone ponownie)
    - Resetuje status raportu na 'running'
    - Uruchamia kontynuowanie sprawdzania
    """
    try:
        result = price_report_admin.restart_report(report_id)
        flash(result.message, result.category)
    except Exception as exc:
        logger.exception("Blad restartowania raportu")
        flash(f"Blad: {exc}", "error")
    
    return redirect(url_for("price_reports.report_detail", report_id=report_id))


@bp.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    """Ustawienia raportow cenowych."""
    if request.method == "POST":
        try:
            result = price_report_admin.update_max_discount(
                request.form.get("max_discount", "5")
            )
            flash(result.message, result.category)
        except Exception as exc:
            logger.exception("Blad zapisu ustawien raportow cenowych")
            flash(f"Blad zapisu: {exc}", "error")
        
        return redirect(url_for("price_reports.settings"))
    
    current_max_discount = get_max_discount_percent()
    excluded_sellers = price_report_admin.list_excluded_sellers()
    
    return render_template(
        "price_reports/settings.html",
        max_discount=current_max_discount,
        excluded_sellers=excluded_sellers,
    )


@bp.route("/exclude-seller", methods=["POST"])
@login_required
def exclude_seller():
    """Dodaje sprzedawce do listy wykluczonych."""
    try:
        result = price_report_admin.exclude_seller(
            request.form.get("seller_name", ""),
            request.form.get("reason", ""),
        )
        flash(result.message, result.category)
    except Exception as exc:
        logger.exception("Blad wykluczania sprzedawcy")
        flash(f"Blad: {exc}", "error")
    
    return redirect(url_for("price_reports.settings"))


@bp.route("/remove-excluded-seller/<int:seller_id>", methods=["POST"])
@login_required
def remove_excluded_seller(seller_id):
    """Usuwa sprzedawce z listy wykluczonych."""
    try:
        result = price_report_admin.remove_excluded_seller(seller_id)
        flash(result.message, result.category)
    except Exception as exc:
        logger.exception("Blad usuwania wykluczenia")
        flash(f"Blad: {exc}", "error")
    
    return redirect(url_for("price_reports.settings"))


@bp.route("/recheck-item/<int:item_id>", methods=["POST"])
@login_required
def recheck_item(item_id):
    """Ponownie sprawdza cene produktu (natychmiast, bez kolejki).
    
    Dodatkowo:
    - Pobiera aktualna cene naszej oferty z Allegro i aktualizuje jesli sie zmienila
    - Przelicza statystyki raportu
    """
    return jsonify(recheck_report_item(item_id, max_discount_provider=get_max_discount_percent))


@bp.route("/change-price/<int:item_id>", methods=["POST"])
@login_required
def change_price(item_id):
    """Zmienia cene oferty na Allegro z weryfikacja przez API.

    Serwis mutacji pobiera nazwe oferty z ``item.product_name``.
    """
    return jsonify(change_report_item_price(item_id, request.form.get("new_price")))


@bp.route("/calculate-profit/<int:item_id>")
@login_required
def calculate_profit(item_id):
    """Oblicza zysk dla aktualnej i proponowanej ceny."""
    
    try:
        with get_session() as session:
            item = session.query(PriceReportItem).filter(
                PriceReportItem.id == item_id
            ).first()
            
            if not item:
                return jsonify({"success": False, "error": "Nie znaleziono pozycji"})
            
            data = calculate_report_item_profit(
                session,
                item,
                packaging_cost=settings_store.get("PACKAGING_COST") or "0.16",
            )
            
            return jsonify({
                "success": True,
                "data": data,
            })
            
    except Exception as e:
        logger.error(f"Blad obliczania zysku: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)})
