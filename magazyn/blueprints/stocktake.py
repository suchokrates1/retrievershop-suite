"""
Blueprint remanentu - inwentaryzacja z ciąglym skanowaniem kodow kreskowych.

Funkcjonalnosc:
- Rozpoczecie nowej sesji remanentu
- Ciagly skan EAN z potwierdzeniem TTS
- Cofnij ostatni skan
- Zakonczenie remanentu i generowanie raportu
- Eksport raportu do PDF
"""
import json
import logging
from datetime import datetime

from flask import (
    Blueprint,
    render_template,
    request,
    jsonify,
    redirect,
    url_for,
    flash,
    session,
    g,
    make_response,
)
from sqlalchemy import func

from ..db import get_session
from ..auth import login_required
from ..models import (
    Product,
    ProductSize,
    Stocktake,
    StocktakeItem,
)
from ..domain.products import find_by_barcode

logger = logging.getLogger(__name__)

bp = Blueprint("stocktake", __name__)


@bp.route("/stocktake")
@login_required
def stocktake_list():
    """Lista remamentow z opcja rozpoczecia nowego."""
    with get_session() as db:
        stocktakes = (
            db.query(Stocktake)
            .order_by(Stocktake.started_at.desc())
            .all()
        )
        items = []
        for st in stocktakes:
            total_items = len(st.items)
            discrepancies = sum(
                1 for item in st.items if item.scanned_qty != item.expected_qty
            )
            items.append({
                "id": st.id,
                "started_at": st.started_at,
                "finished_at": st.finished_at,
                "status": st.status,
                "total_items": total_items,
                "discrepancies": discrepancies,
                "notes": st.notes,
            })
    return render_template("stocktake_list.html", stocktakes=items)


@bp.route("/stocktake/new", methods=["POST"])
@login_required
def stocktake_new():
    """Rozpocznij nowy remanent."""
    user_id = session.get("user_id")
    with get_session() as db:
        # Sprawdz czy jest juz aktywny remanent
        active = (
            db.query(Stocktake)
            .filter_by(status="in_progress")
            .first()
        )
        if active:
            flash("Istnieje juz aktywny remanent. Zakoncz go przed rozpoczeciem nowego.", "warning")
            return redirect(url_for("stocktake.stocktake_scan", stocktake_id=active.id))

        st = Stocktake(
            status="in_progress",
            user_id=user_id,
        )
        db.add(st)
        db.flush()

        # Zapisz oczekiwane ilosci ze stanu magazynowego
        sizes = (
            db.query(ProductSize)
            .filter(ProductSize.barcode.isnot(None))
            .filter(ProductSize.barcode != "")
            .all()
        )
        for ps in sizes:
            item = StocktakeItem(
                stocktake_id=st.id,
                product_size_id=ps.id,
                expected_qty=ps.quantity,
                scanned_qty=0,
            )
            db.add(item)

        stocktake_id = st.id

    return redirect(url_for("stocktake.stocktake_scan", stocktake_id=stocktake_id))


@bp.route("/stocktake/<int:stocktake_id>/scan")
@login_required
def stocktake_scan(stocktake_id):
    """Strona ciąglego skanowania remanentu."""
    with get_session() as db:
        st = db.query(Stocktake).get(stocktake_id)
        if not st:
            flash("Remanent nie znaleziony.", "danger")
            return redirect(url_for("stocktake.stocktake_list"))
        if st.status != "in_progress":
            return redirect(url_for("stocktake.stocktake_report", stocktake_id=stocktake_id))

        # Zbierz podsumowanie
        total_products = len(st.items)
        scanned_products = sum(1 for item in st.items if item.scanned_qty > 0)
        total_scanned = sum(item.scanned_qty for item in st.items)

    return render_template(
        "stocktake_scan.html",
        stocktake_id=stocktake_id,
        total_products=total_products,
        scanned_products=scanned_products,
        total_scanned=total_scanned,
    )


@bp.route("/stocktake/<int:stocktake_id>/barcode_scan", methods=["POST"])
@login_required
def stocktake_barcode_scan(stocktake_id):
    """Endpoint skanowania kodu EAN podczas remanentu."""
    data = request.get_json(silent=True) or {}
    barcode = (data.get("barcode") or "").strip()

    if not barcode:
        return jsonify({"error": "Brak kodu kreskowego"}), 400

    with get_session() as db:
        st = db.query(Stocktake).get(stocktake_id)
        if not st or st.status != "in_progress":
            return jsonify({"error": "Remanent nie jest aktywny"}), 400

        # Znajdz ProductSize po kodzie kreskowym
        ps = (
            db.query(ProductSize)
            .filter_by(barcode=barcode)
            .first()
        )
        if not ps:
            return jsonify({
                "error": f"Nie znaleziono produktu o kodzie {barcode}"
            }), 404

        product = ps.product

        # Znajdz lub stworz pozycje remanentu
        item = (
            db.query(StocktakeItem)
            .filter_by(stocktake_id=stocktake_id, product_size_id=ps.id)
            .first()
        )
        if not item:
            # Produkt bez kodu w momencie startu remanentu - dodaj
            item = StocktakeItem(
                stocktake_id=stocktake_id,
                product_size_id=ps.id,
                expected_qty=ps.quantity,
                scanned_qty=0,
            )
            db.add(item)
            db.flush()

        item.scanned_qty += 1
        item.scanned_at = datetime.now()

        scanned = item.scanned_qty
        expected = item.expected_qty

        # Buduj dane TTS
        tts_parts = []
        if product.series:
            tts_parts.append(product.series)
        elif product.category:
            tts_parts.append(product.category)
        if ps.size and ps.size != "Uniwersalny":
            tts_parts.append(ps.size)
        if product.color:
            tts_parts.append(product.color)
        tts_name = " ".join(tts_parts) if tts_parts else "Produkt"

        # Komunikat TTS
        if scanned > expected:
            tts_message = f"{tts_name}. {scanned} z {expected}. Nadwyzka!"
        elif scanned == expected:
            tts_message = f"{tts_name}. {scanned} z {expected}. OK"
        else:
            tts_message = f"{tts_name}. {scanned} z {expected}"

        # Zbierz podsumowanie
        total_products = db.query(StocktakeItem).filter_by(stocktake_id=stocktake_id).count()
        scanned_products = (
            db.query(StocktakeItem)
            .filter_by(stocktake_id=stocktake_id)
            .filter(StocktakeItem.scanned_qty > 0)
            .count()
        )
        total_scanned = (
            db.query(func.sum(StocktakeItem.scanned_qty))
            .filter_by(stocktake_id=stocktake_id)
            .scalar() or 0
        )

        return jsonify({
            "success": True,
            "tts_message": tts_message,
            "product_name": product.name,
            "color": product.color or "",
            "size": ps.size or "",
            "series": product.series or "",
            "scanned_qty": scanned,
            "expected_qty": expected,
            "item_id": item.id,
            "total_products": total_products,
            "scanned_products": scanned_products,
            "total_scanned": total_scanned,
        })


@bp.route("/stocktake/<int:stocktake_id>/undo", methods=["POST"])
@login_required
def stocktake_undo(stocktake_id):
    """Cofnij ostatni skan."""
    with get_session() as db:
        st = db.query(Stocktake).get(stocktake_id)
        if not st or st.status != "in_progress":
            return jsonify({"error": "Remanent nie jest aktywny"}), 400

        # Znajdz ostatnio zeskanowana pozycje
        last_item = (
            db.query(StocktakeItem)
            .filter_by(stocktake_id=stocktake_id)
            .filter(StocktakeItem.scanned_qty > 0)
            .filter(StocktakeItem.scanned_at.isnot(None))
            .order_by(StocktakeItem.scanned_at.desc())
            .first()
        )
        if not last_item:
            return jsonify({"error": "Brak skanow do cofniecia"}), 400

        last_item.scanned_qty -= 1

        ps = db.query(ProductSize).get(last_item.product_size_id)
        product = ps.product if ps else None
        product_name = product.name if product else "Nieznany"
        size = ps.size if ps else ""
        color = product.color if product else ""

        # Podsumowanie
        total_products = db.query(StocktakeItem).filter_by(stocktake_id=stocktake_id).count()
        scanned_products = (
            db.query(StocktakeItem)
            .filter_by(stocktake_id=stocktake_id)
            .filter(StocktakeItem.scanned_qty > 0)
            .count()
        )
        total_scanned = (
            db.query(func.sum(StocktakeItem.scanned_qty))
            .filter_by(stocktake_id=stocktake_id)
            .scalar() or 0
        )

        return jsonify({
            "success": True,
            "message": f"Cofnieto skan: {product_name} {size} {color}",
            "tts_message": f"Cofnieto. {product_name}",
            "scanned_qty": last_item.scanned_qty,
            "expected_qty": last_item.expected_qty,
            "total_products": total_products,
            "scanned_products": scanned_products,
            "total_scanned": total_scanned,
        })


@bp.route("/stocktake/<int:stocktake_id>/finish", methods=["POST"])
@login_required
def stocktake_finish(stocktake_id):
    """Zakoncz remanent."""
    with get_session() as db:
        st = db.query(Stocktake).get(stocktake_id)
        if not st:
            flash("Remanent nie znaleziony.", "danger")
            return redirect(url_for("stocktake.stocktake_list"))

        st.status = "finished"
        st.finished_at = datetime.now()

        data = request.get_json(silent=True) or {}
        if data.get("notes"):
            st.notes = data["notes"]

    if request.is_json:
        return jsonify({"success": True, "redirect": url_for("stocktake.stocktake_report", stocktake_id=stocktake_id)})
    return redirect(url_for("stocktake.stocktake_report", stocktake_id=stocktake_id))


@bp.route("/stocktake/<int:stocktake_id>/report")
@login_required
def stocktake_report(stocktake_id):
    """Raport z remanentu - porownanie oczekiwanego z zeskanowanym."""
    with get_session() as db:
        st = db.query(Stocktake).get(stocktake_id)
        if not st:
            flash("Remanent nie znaleziony.", "danger")
            return redirect(url_for("stocktake.stocktake_list"))

        report_items = []
        for item in st.items:
            ps = item.product_size
            product = ps.product if ps else None
            diff = item.scanned_qty - item.expected_qty
            report_items.append({
                "product_name": product.name if product else "Nieznany",
                "series": product.series if product else "",
                "category": product.category if product else "",
                "color": product.color if product else "",
                "size": ps.size if ps else "",
                "barcode": ps.barcode if ps else "",
                "expected_qty": item.expected_qty,
                "scanned_qty": item.scanned_qty,
                "difference": diff,
                "status": "ok" if diff == 0 else ("nadwyzka" if diff > 0 else "brak"),
            })

        # Sortuj: najpierw rozbieznosci, potem po nazwie
        report_items.sort(key=lambda x: (x["status"] == "ok", x["product_name"], x["size"]))

        total_expected = sum(i["expected_qty"] for i in report_items)
        total_scanned = sum(i["scanned_qty"] for i in report_items)
        total_discrepancies = sum(1 for i in report_items if i["difference"] != 0)

        stocktake_data = {
            "id": st.id,
            "started_at": st.started_at,
            "finished_at": st.finished_at,
            "status": st.status,
            "notes": st.notes,
        }

    return render_template(
        "stocktake_report.html",
        stocktake=stocktake_data,
        items=report_items,
        total_expected=total_expected,
        total_scanned=total_scanned,
        total_discrepancies=total_discrepancies,
    )


@bp.route("/stocktake/<int:stocktake_id>/apply", methods=["POST"])
@login_required
def stocktake_apply(stocktake_id):
    """Zastosuj wyniki remanentu - zaktualizuj stany magazynowe."""
    with get_session() as db:
        st = db.query(Stocktake).get(stocktake_id)
        if not st or st.status != "finished":
            flash("Mozna aplikowac tylko zakonczony remanent.", "warning")
            return redirect(url_for("stocktake.stocktake_list"))

        updated = 0
        for item in st.items:
            if item.scanned_qty != item.expected_qty:
                ps = db.query(ProductSize).get(item.product_size_id)
                if ps:
                    ps.quantity = item.scanned_qty
                    updated += 1

        st.status = "applied"

    flash(f"Zaktualizowano stany {updated} produktow na podstawie remanentu.", "success")
    return redirect(url_for("stocktake.stocktake_report", stocktake_id=stocktake_id))


@bp.route("/stocktake/<int:stocktake_id>/pdf")
@login_required
def stocktake_pdf(stocktake_id):
    """Eksport raportu remanentu do PDF."""
    with get_session() as db:
        st = db.query(Stocktake).get(stocktake_id)
        if not st:
            flash("Remanent nie znaleziony.", "danger")
            return redirect(url_for("stocktake.stocktake_list"))

        report_items = []
        for item in st.items:
            ps = item.product_size
            product = ps.product if ps else None
            diff = item.scanned_qty - item.expected_qty
            report_items.append({
                "product_name": product.name if product else "Nieznany",
                "series": product.series if product else "",
                "color": product.color if product else "",
                "size": ps.size if ps else "",
                "barcode": ps.barcode if ps else "",
                "expected_qty": item.expected_qty,
                "scanned_qty": item.scanned_qty,
                "difference": diff,
            })

        report_items.sort(key=lambda x: (x["difference"] == 0, x["product_name"], x["size"]))

        total_expected = sum(i["expected_qty"] for i in report_items)
        total_scanned = sum(i["scanned_qty"] for i in report_items)

        started = st.started_at.strftime("%Y-%m-%d %H:%M") if st.started_at else ""
        finished = st.finished_at.strftime("%Y-%m-%d %H:%M") if st.finished_at else ""

    # Generuj PDF
    html_content = _build_pdf_html(
        stocktake_id, started, finished, report_items, total_expected, total_scanned
    )

    try:
        from weasyprint import HTML
        pdf_bytes = HTML(string=html_content).write_pdf()
    except ImportError:
        # Fallback: zwroc HTML do wydruku
        response = make_response(html_content)
        response.headers["Content-Type"] = "text/html; charset=utf-8"
        return response

    response = make_response(pdf_bytes)
    response.headers["Content-Type"] = "application/pdf"
    response.headers["Content-Disposition"] = f"attachment; filename=remanent_{stocktake_id}_{started[:10]}.pdf"
    return response


def _build_pdf_html(stocktake_id, started, finished, items, total_expected, total_scanned):
    """Buduj HTML dla raportu PDF remanentu."""
    discrepancies = sum(1 for i in items if i["difference"] != 0)

    rows_html = ""
    for idx, item in enumerate(items, 1):
        diff = item["difference"]
        if diff < 0:
            diff_style = "color: red; font-weight: bold;"
            diff_text = str(diff)
        elif diff > 0:
            diff_style = "color: blue; font-weight: bold;"
            diff_text = f"+{diff}"
        else:
            diff_style = ""
            diff_text = "0"

        rows_html += f"""
        <tr>
            <td>{idx}</td>
            <td>{item['product_name']}</td>
            <td>{item['color']}</td>
            <td>{item['size']}</td>
            <td>{item['barcode']}</td>
            <td style="text-align:center">{item['expected_qty']}</td>
            <td style="text-align:center">{item['scanned_qty']}</td>
            <td style="text-align:center; {diff_style}">{diff_text}</td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html lang="pl">
<head>
    <meta charset="utf-8">
    <title>Raport remanentu #{stocktake_id}</title>
    <style>
        body {{ font-family: Arial, sans-serif; font-size: 11px; margin: 20px; }}
        h1 {{ font-size: 18px; text-align: center; margin-bottom: 5px; }}
        .info {{ text-align: center; margin-bottom: 15px; font-size: 12px; }}
        table {{ width: 100%; border-collapse: collapse; margin-bottom: 20px; }}
        th, td {{ border: 1px solid #333; padding: 4px 6px; text-align: left; }}
        th {{ background-color: #f0f0f0; font-weight: bold; }}
        .summary {{ margin-top: 20px; }}
        .signatures {{ margin-top: 60px; display: flex; justify-content: space-between; }}
        .signature-box {{ text-align: center; width: 40%; }}
        .signature-line {{ border-top: 1px solid #333; margin-top: 40px; padding-top: 5px; }}
    </style>
</head>
<body>
    <h1>Protokol inwentaryzacji magazynu</h1>
    <div class="info">
        Remanent nr {stocktake_id} |
        Rozpoczeto: {started} |
        Zakonczono: {finished}
    </div>

    <table>
        <thead>
            <tr>
                <th>Lp.</th>
                <th>Nazwa produktu</th>
                <th>Kolor</th>
                <th>Rozmiar</th>
                <th>EAN</th>
                <th style="text-align:center">Stan wg systemu</th>
                <th style="text-align:center">Stan faktyczny</th>
                <th style="text-align:center">Roznica</th>
            </tr>
        </thead>
        <tbody>
            {rows_html}
        </tbody>
    </table>

    <div class="summary">
        <p><strong>Podsumowanie:</strong></p>
        <p>Ilosc pozycji: {len(items)}</p>
        <p>Laczny stan wg systemu: {total_expected}</p>
        <p>Laczny stan faktyczny: {total_scanned}</p>
        <p>Pozycje z rozbieznosciami: {discrepancies}</p>
    </div>

    <div class="signatures" style="display:flex; justify-content:space-between; margin-top:60px;">
        <div class="signature-box" style="text-align:center; width:40%;">
            <div class="signature-line" style="border-top:1px solid #333; margin-top:40px; padding-top:5px;">
                Sporządzil(a)
            </div>
        </div>
        <div class="signature-box" style="text-align:center; width:40%;">
            <div class="signature-line" style="border-top:1px solid #333; margin-top:40px; padding-top:5px;">
                Zatwierdzil(a)
            </div>
        </div>
    </div>
</body>
</html>"""
