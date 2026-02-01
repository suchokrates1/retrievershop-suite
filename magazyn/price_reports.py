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
    current_app,
    flash,
    redirect,
    url_for,
)
from datetime import datetime
from decimal import Decimal
import json
import logging
import asyncio

from .auth import login_required
from .db import get_session
from .models import (
    PriceReport,
    PriceReportItem,
    AllegroOffer,
    Product,
    ProductSize,
    ExcludedSeller,
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
    filter_mode = request.args.get("filter", "all")  # all, not_cheapest, cheapest, errors
    
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
        elif filter_mode == "errors":
            query = query.filter(PriceReportItem.error != None)
        
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
            "errors": sum(1 for i in items if i.error),
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


@bp.route("/restart/<int:report_id>", methods=["POST"])
@login_required
def restart_report(report_id):
    """Restartuje raport - sprawdza niesprawdzone oferty i te z bledami.
    
    - Usuwa wpisy z bledami (zeby mogly byc sprawdzone ponownie)
    - Resetuje status raportu na 'running'
    - Uruchamia kontynuowanie sprawdzania
    """
    from .price_report_scheduler import restart_price_report
    
    try:
        result = restart_price_report(report_id)
        if result.get("success"):
            flash(f"Zrestartowano raport #{report_id}: {result.get('removed_errors', 0)} bledow usunieto, {result.get('remaining', 0)} do sprawdzenia", "success")
        else:
            flash(result.get("error", "Nieznany blad"), "error")
    except Exception as e:
        logger.error(f"Blad restartowania raportu: {e}", exc_info=True)
        flash(f"Blad: {e}", "error")
    
    return redirect(url_for("price_reports.report_detail", report_id=report_id))


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
    
    # Pobierz liste wykluczonych sprzedawcow
    with get_session() as session:
        excluded_sellers = session.query(ExcludedSeller).order_by(
            ExcludedSeller.excluded_at.desc()
        ).all()
    
    return render_template(
        "price_reports/settings.html",
        max_discount=current_max_discount,
        excluded_sellers=excluded_sellers,
    )


@bp.route("/exclude-seller", methods=["POST"])
@login_required
def exclude_seller():
    """Dodaje sprzedawce do listy wykluczonych."""
    seller_name = request.form.get("seller_name", "").strip()
    reason = request.form.get("reason", "").strip() or None
    
    if not seller_name:
        flash("Podaj nazwe sprzedawcy", "error")
        return redirect(url_for("price_reports.settings"))
    
    try:
        with get_session() as session:
            # Sprawdz czy juz wykluczony
            existing = session.query(ExcludedSeller).filter(
                ExcludedSeller.seller_name == seller_name
            ).first()
            
            if existing:
                flash(f"Sprzedawca '{seller_name}' juz jest wykluczony", "warning")
            else:
                excluded = ExcludedSeller(
                    seller_name=seller_name,
                    reason=reason
                )
                session.add(excluded)
                session.commit()
                flash(f"Wykluczono sprzedawce '{seller_name}'", "success")
    except Exception as e:
        logger.error(f"Blad wykluczania sprzedawcy: {e}", exc_info=True)
        flash(f"Blad: {e}", "error")
    
    return redirect(url_for("price_reports.settings"))


@bp.route("/remove-excluded-seller/<int:seller_id>", methods=["POST"])
@login_required
def remove_excluded_seller(seller_id):
    """Usuwa sprzedawce z listy wykluczonych."""
    try:
        with get_session() as session:
            seller = session.query(ExcludedSeller).filter(
                ExcludedSeller.id == seller_id
            ).first()
            
            if seller:
                name = seller.seller_name
                session.delete(seller)
                session.commit()
                flash(f"Usunieto '{name}' z listy wykluczonych", "success")
            else:
                flash("Nie znaleziono sprzedawcy", "error")
    except Exception as e:
        logger.error(f"Blad usuwania wykluczenia: {e}", exc_info=True)
        flash(f"Blad: {e}", "error")
    
    return redirect(url_for("price_reports.settings"))


@bp.route("/recheck-item/<int:item_id>", methods=["POST"])
@login_required
def recheck_item(item_id):
    """Ponownie sprawdza cene produktu (natychmiast, bez kolejki).
    
    Dodatkowo:
    - Pobiera aktualna cene naszej oferty z Allegro i aktualizuje jesli sie zmienila
    - Przelicza statystyki raportu
    """
    from .scripts.price_checker_ws import check_offer_price, CDP_HOST, CDP_PORT, MAX_DELIVERY_DAYS
    from .allegro_api.offers import get_offer_details
    
    try:
        with get_session() as session:
            item = session.query(PriceReportItem).filter(
                PriceReportItem.id == item_id
            ).first()
            
            if not item:
                return jsonify({"success": False, "error": "Nie znaleziono pozycji"})
            
            report_id = item.report_id
            offer_id = item.offer_id
            old_our_price = float(item.our_price) if item.our_price else None
            title = item.product_name
        
        # Najpierw pobierz aktualna cene naszej oferty z Allegro API
        our_offer_data = get_offer_details(offer_id)
        current_our_price = old_our_price
        price_updated = False
        
        if our_offer_data.get("success") and our_offer_data.get("price"):
            current_our_price = float(our_offer_data["price"])
            if old_our_price and abs(current_our_price - old_our_price) > 0.001:
                price_updated = True
                logger.info(f"Cena oferty {offer_id} zmienila sie: {old_our_price} -> {current_our_price}")
        
        # Uruchom sprawdzenie konkurencji
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(
            check_offer_price(offer_id, title, current_our_price, CDP_HOST, CDP_PORT, MAX_DELIVERY_DAYS)
        )
        loop.close()
        
        # Zaktualizuj wynik w bazie
        with get_session() as session:
            item = session.query(PriceReportItem).filter(
                PriceReportItem.id == item_id
            ).first()
            
            # Zaktualizuj nasza cene jesli sie zmienila
            if price_updated:
                item.our_price = Decimal(str(current_our_price))
                # Zaktualizuj tez w tabeli AllegroOffer
                offer = session.query(AllegroOffer).filter(
                    AllegroOffer.offer_id == offer_id
                ).first()
                if offer:
                    offer.price = Decimal(str(current_our_price))
            
            if result.success and result.cheapest_competitor:
                item.competitor_price = Decimal(str(result.cheapest_competitor.price))
                item.competitor_seller = result.cheapest_competitor.seller
                item.competitor_url = result.cheapest_competitor.offer_url
                item.our_position = result.my_position
                item.total_offers = len(result.competitors) + 1 if result.competitors else 1
                
                if item.our_price:
                    item.is_cheapest = item.our_price <= item.competitor_price
                    item.price_difference = float(item.our_price - item.competitor_price)
                
                item.error = None
            elif result.success and not result.cheapest_competitor:
                # Brak konkurencji - jestesmy jedyni
                item.competitor_price = None
                item.competitor_seller = None
                item.competitor_url = None
                item.our_position = 1
                item.total_offers = 1
                item.is_cheapest = True
                item.price_difference = None
                item.error = None
            else:
                item.error = result.error or "Blad sprawdzania"
            
            item.checked_at = datetime.now()
            session.commit()
            
            # Przygotuj odpowiedz
            max_discount = get_max_discount_percent()
            suggestion = None
            if not item.is_cheapest and item.competitor_price and item.our_price:
                target_price = float(item.competitor_price) - 0.01
                discount_needed = ((float(item.our_price) - target_price) / float(item.our_price)) * 100
                if discount_needed <= max_discount:
                    suggestion = {
                        "target_price": round(target_price, 2),
                        "discount_percent": round(discount_needed, 2),
                    }
            
            return jsonify({
                "success": True,
                "price_updated": price_updated,
                "old_price": old_our_price,
                "data": {
                    "our_price": float(item.our_price) if item.our_price else None,
                    "competitor_price": float(item.competitor_price) if item.competitor_price else None,
                    "competitor_seller": item.competitor_seller,
                    "is_cheapest": item.is_cheapest,
                    "price_difference": item.price_difference,
                    "our_position": item.our_position,
                    "total_offers": item.total_offers,
                    "suggestion": suggestion,
                    "error": item.error,
                }
            })
            
    except Exception as e:
        logger.error(f"Blad ponownego sprawdzania: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)})


@bp.route("/change-price/<int:item_id>", methods=["POST"])
@login_required
def change_price(item_id):
    """Zmienia cene oferty na Allegro."""
    from .allegro_api.offers import change_offer_price
    
    new_price = request.form.get("new_price")
    if not new_price:
        return jsonify({"success": False, "error": "Podaj nowa cene"})
    
    try:
        new_price = Decimal(new_price)
    except:
        return jsonify({"success": False, "error": "Nieprawidlowa cena"})
    
    try:
        with get_session() as session:
            item = session.query(PriceReportItem).filter(
                PriceReportItem.id == item_id
            ).first()
            
            if not item:
                return jsonify({"success": False, "error": "Nie znaleziono pozycji"})
            
            offer_id = item.offer_id
            old_price = item.our_price
        
        # Zmien cene przez API
        result = change_offer_price(offer_id, new_price)
        
        if result.get("success"):
            # Zaktualizuj w bazie lokalnej
            with get_session() as session:
                # Zaktualizuj PriceReportItem
                item = session.query(PriceReportItem).filter(
                    PriceReportItem.id == item_id
                ).first()
                if item:
                    item.our_price = new_price
                    if item.competitor_price:
                        item.is_cheapest = new_price <= item.competitor_price
                        item.price_difference = float(new_price - item.competitor_price)
                
                # Zaktualizuj AllegroOffer
                offer = session.query(AllegroOffer).filter(
                    AllegroOffer.offer_id == offer_id
                ).first()
                if offer:
                    offer.price = new_price
                
                session.commit()
            
            return jsonify({
                "success": True,
                "message": f"Zmieniono cene z {old_price} na {new_price} zl"
            })
        else:
            return jsonify({
                "success": False,
                "error": result.get("error", "Blad API Allegro")
            })
            
    except Exception as e:
        logger.error(f"Blad zmiany ceny: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)})


@bp.route("/calculate-profit/<int:item_id>")
@login_required
def calculate_profit(item_id):
    """Oblicza zysk dla aktualnej i proponowanej ceny."""
    from .services.order_detail_builder import OrderDetailBuilder
    
    try:
        with get_session() as session:
            item = session.query(PriceReportItem).filter(
                PriceReportItem.id == item_id
            ).first()
            
            if not item:
                return jsonify({"success": False, "error": "Nie znaleziono pozycji"})
            
            offer_id = item.offer_id
            our_price = float(item.our_price) if item.our_price else 0
            competitor_price = float(item.competitor_price) if item.competitor_price else 0
            
            # Pobierz oferte i produkt
            offer = session.query(AllegroOffer).filter(
                AllegroOffer.offer_id == offer_id
            ).first()
            
            if not offer or not offer.product_size_id:
                # Fallback - liczymy bez danych o produkcie
                return _calculate_fallback_profit(our_price, competitor_price)
            
            # Pobierz dane produktu
            product_size = session.query(ProductSize).filter(
                ProductSize.id == offer.product_size_id
            ).first()
            
            if not product_size:
                return _calculate_fallback_profit(our_price, competitor_price)
            
            # Srednia cena zakupu
            purchase_price = float(product_size.avg_purchase_price or 0)
            
            # Koszty wysylki (z progow)
            from .models import ShippingThreshold
            thresholds = session.query(ShippingThreshold).order_by(
                ShippingThreshold.min_order_value.desc()
            ).all()
            
            shipping_cost = Decimal("8.99")  # Domyslny
            for t in thresholds:
                if our_price >= t.min_order_value:
                    shipping_cost = t.shipping_cost
                    break
            
            # Koszt pakowania
            packaging_cost = Decimal(str(settings_store.get("PACKAGING_COST") or "0.16"))
            
            # Prowizja Allegro ~12.3% + 1zl (uproszczony model)
            allegro_fee_percent = Decimal("0.123")
            allegro_fixed_fee = Decimal("1.0")
            
            def calc_profit(price):
                price = Decimal(str(price))
                allegro_fees = price * allegro_fee_percent + allegro_fixed_fee
                return float(price - Decimal(str(purchase_price)) - allegro_fees - packaging_cost)
            
            current_profit = calc_profit(our_price)
            target_price = competitor_price - 0.01 if competitor_price > 0 else our_price
            new_profit = calc_profit(target_price)
            
            price_change_percent = ((our_price - target_price) / our_price * 100) if our_price > 0 else 0
            
            return jsonify({
                "success": True,
                "data": {
                    "current_price": our_price,
                    "target_price": round(target_price, 2),
                    "price_change_percent": round(price_change_percent, 2),
                    "current_profit": round(current_profit, 2),
                    "new_profit": round(new_profit, 2),
                    "profit_change": round(new_profit - current_profit, 2),
                    "purchase_price": purchase_price,
                    "competitor_price": competitor_price,
                }
            })
            
    except Exception as e:
        logger.error(f"Blad obliczania zysku: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)})


def _calculate_fallback_profit(our_price: float, competitor_price: float) -> dict:
    """Oblicza zysk bez danych produktu (fallback)."""
    # Fallback: zakladamy prowizje 12.3% + 1zl + wysylka 8.99 + pakowanie 0.16
    allegro_fee_percent = 0.123
    allegro_fixed_fee = 1.0
    shipping = 8.99
    packaging = 0.16
    
    def calc(price):
        allegro_fees = price * allegro_fee_percent + allegro_fixed_fee
        # Bez ceny zakupu - pokazujemy tylko koszty
        return price - allegro_fees - packaging
    
    target_price = competitor_price - 0.01 if competitor_price > 0 else our_price
    price_change_percent = ((our_price - target_price) / our_price * 100) if our_price > 0 else 0
    
    return jsonify({
        "success": True,
        "data": {
            "current_price": our_price,
            "target_price": round(target_price, 2),
            "price_change_percent": round(price_change_percent, 2),
            "current_profit": round(calc(our_price), 2),
            "new_profit": round(calc(target_price), 2),
            "profit_change": round(calc(target_price) - calc(our_price), 2),
            "purchase_price": None,
            "competitor_price": competitor_price,
            "note": "Brak danych o cenie zakupu - pokazano zysk bez kosztu towaru"
        }
    })
