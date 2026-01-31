"""
Blueprint i logika dla raportow cenowych.

Funkcjonalnosci:
- Wyswietlanie raportow cenowych
- Filtrowanie (tylko gdzie nie jestesmy najtansi)
- Historia raportow
- Sugestie cen
"""

from flask import (
    Blueprint,
    render_template,
    request,
    jsonify,
    current_app,
    flash,
    redirect,
    url_for,
)
from datetime import datetime
from decimal import Decimal
import json
import logging

from .auth import login_required
from .db import get_session
from .models import (
    PriceReport,
    PriceReportItem,
    AllegroOffer,
    Product,
    ProductSize,
)
from .settings_store import settings_store

logger = logging.getLogger(__name__)

bp = Blueprint("price_reports", __name__, url_prefix="/price-reports")


def get_max_discount_percent() -> float:
    """Pobiera maksymalny procent znizki z ustawien."""
    try:
        value = settings_store.get("PRICE_MAX_DISCOUNT_PERCENT", "5")
        return float(value)
    except (ValueError, TypeError):
        return 5.0


@bp.route("/")
@login_required
def reports_list():
    """Lista wszystkich raportow cenowych."""
    with get_session() as session:
        reports = session.query(PriceReport).order_by(
            PriceReport.created_at.desc()
        ).all()
        
        reports_data = []
        for report in reports:
            items_count = session.query(PriceReportItem).filter(
                PriceReportItem.report_id == report.id
            ).count()
            
            cheaper_count = session.query(PriceReportItem).filter(
                PriceReportItem.report_id == report.id,
                PriceReportItem.is_cheapest == True
            ).count()
            
            reports_data.append({
                "id": report.id,
                "created_at": report.created_at,
                "completed_at": report.completed_at,
                "status": report.status,
                "items_checked": report.items_checked,
                "items_total": report.items_total,
                "total_offers": items_count,
                "we_are_cheapest": cheaper_count,
                "we_are_not_cheapest": items_count - cheaper_count,
            })
        
        return render_template(
            "price_reports/reports_list.html",
            reports=reports_data
        )


@bp.route("/<int:report_id>")
@login_required
def report_detail(report_id: int):
    """Szczegoly raportu cenowego."""
    filter_mode = request.args.get("filter", "all")  # all, not_cheapest, cheapest
    
    with get_session() as session:
        report = session.query(PriceReport).filter(
            PriceReport.id == report_id
        ).first()
        
        if not report:
            flash("Raport nie istnieje", "error")
            return redirect(url_for("price_reports.reports_list"))
        
        query = session.query(PriceReportItem).filter(
            PriceReportItem.report_id == report_id
        )
        
        if filter_mode == "not_cheapest":
            query = query.filter(PriceReportItem.is_cheapest == False)
        elif filter_mode == "cheapest":
            query = query.filter(PriceReportItem.is_cheapest == True)
        
        items = query.order_by(PriceReportItem.price_difference.desc()).all()
        
        max_discount = get_max_discount_percent()
        
        items_data = []
        for item in items:
            # Oblicz sugestie ceny
            suggestion = None
            if not item.is_cheapest and item.competitor_price and item.our_price:
                target_price = float(item.competitor_price) - 0.01
                discount_needed = ((float(item.our_price) - target_price) / float(item.our_price)) * 100
                
                if discount_needed <= max_discount:
                    suggestion = {
                        "target_price": round(target_price, 2),
                        "discount_percent": round(discount_needed, 2),
                        "savings": round(float(item.our_price) - target_price, 2),
                    }
            
            items_data.append({
                "id": item.id,
                "offer_id": item.offer_id,
                "product_name": item.product_name,
                "our_price": item.our_price,
                "competitor_price": item.competitor_price,
                "competitor_seller": item.competitor_seller,
                "competitor_url": item.competitor_url,
                "is_cheapest": item.is_cheapest,
                "price_difference": item.price_difference,
                "our_position": item.our_position,
                "total_offers": item.total_offers,
                "suggestion": suggestion,
                "checked_at": item.checked_at,
                "error": item.error,
            })
        
        stats = {
            "total": len(items),
            "cheapest": sum(1 for i in items if i.is_cheapest),
            "not_cheapest": sum(1 for i in items if not i.is_cheapest),
            "with_suggestion": sum(1 for i in items_data if i.get("suggestion")),
        }
        
        return render_template(
            "price_reports/report_detail.html",
            report=report,
            items=items_data,
            stats=stats,
            filter_mode=filter_mode,
            max_discount=max_discount,
        )


@bp.route("/current-status")
@login_required
def current_status():
    """Zwraca status biezacego raportu (dla AJAX)."""
    with get_session() as session:
        report = session.query(PriceReport).filter(
            PriceReport.status.in_(["pending", "running"])
        ).order_by(PriceReport.created_at.desc()).first()
        
        if not report:
            return jsonify({"status": "none"})
        
        return jsonify({
            "status": report.status,
            "id": report.id,
            "items_checked": report.items_checked,
            "items_total": report.items_total,
            "progress_percent": round(
                (report.items_checked / report.items_total * 100) 
                if report.items_total > 0 else 0, 1
            ),
            "started_at": report.created_at.isoformat() if report.created_at else None,
        })


@bp.route("/start-manual", methods=["POST"])
@login_required
def start_manual_report():
    """Reczne uruchomienie raportu cenowego."""
    from .price_report_scheduler import start_price_report_now
    
    try:
        report_id = start_price_report_now()
        flash(f"Rozpoczeto generowanie raportu #{report_id}", "success")
    except Exception as e:
        logger.error(f"Blad uruchamiania raportu: {e}", exc_info=True)
        flash(f"Blad: {e}", "error")
    
    return redirect(url_for("price_reports.reports_list"))


@bp.route("/resume/<int:report_id>", methods=["POST"])
@login_required
def resume_report(report_id):
    """Wznawia przetwarzanie przerwanego raportu."""
    from .price_report_scheduler import resume_price_report
    
    try:
        resumed_id = resume_price_report(report_id)
        if resumed_id:
            flash(f"Wznowiono raport #{resumed_id}", "success")
        else:
            flash("Nie znaleziono raportu do wznowienia", "error")
    except Exception as e:
        logger.error(f"Blad wznawiania raportu: {e}", exc_info=True)
        flash(f"Blad: {e}", "error")
    
    return redirect(url_for("price_reports.reports_list"))


@bp.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    """Ustawienia raportow cenowych."""
    if request.method == "POST":
        try:
            max_discount = request.form.get("max_discount", "5")
            settings_store.update({
                "PRICE_MAX_DISCOUNT_PERCENT": max_discount,
            })
            flash("Zapisano ustawienia", "success")
        except Exception as e:
            flash(f"Blad zapisu: {e}", "error")
        
        return redirect(url_for("price_reports.settings"))
    
    current_max_discount = get_max_discount_percent()
    
    return render_template(
        "price_reports/settings.html",
        max_discount=current_max_discount,
    )
