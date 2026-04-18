"""Naprawa ostatniego raportu: usun bledne 'Inna OK' dla ofert Cordura.

Po naprawie przypisania product_size_id ofert Cordura, stare wpisy 'Inna OK'
w raporcie sa nieprawidlowe (bazowaly na wspolnym product_size_id z tanszymi
ofertami zwyklych Front Line). Skrypt usunie te wpisy z raportu i zmniejszy
items_checked, zeby restart raportu mogl je ponownie sprawdzic.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from magazyn.db import configure_engine, get_session
from magazyn.models import PriceReport, PriceReportItem, AllegroOffer

configure_engine()

# 4 oferty Cordura ktore byly blednie oznaczone "Inna OK"
CORDURA_OFFER_IDS = ['17768380937', '18370786950', '18332420996', '18358308246']

with get_session() as s:
    # Znajdz ostatni raport
    report = s.query(PriceReport).order_by(PriceReport.id.desc()).first()
    if not report:
        print("Brak raportow!")
        sys.exit(1)
    
    print(f"Ostatni raport: #{report.id} (status={report.status}, {report.items_checked}/{report.items_total})")
    
    removed = 0
    for oid in CORDURA_OFFER_IDS:
        item = s.query(PriceReportItem).filter(
            PriceReportItem.report_id == report.id,
            PriceReportItem.offer_id == oid,
        ).first()
        
        if not item:
            print(f"  {oid}: brak wpisu w raporcie")
            continue
        
        # Sprawdz czy to faktycznie "Inna OK" (brak competitor_price, brak error)
        is_inna_ok = (item.competitor_price is None and item.error is None)
        if is_inna_ok:
            s.delete(item)
            removed += 1
            print(f"  {oid}: USUNIETO wpis 'Inna OK' ({item.product_name[:60]})")
        else:
            print(f"  {oid}: wpis NIE jest 'Inna OK' (competitor_price={item.competitor_price}, error={item.error})")
    
    if removed > 0:
        report.items_checked -= removed
        print(f"\nUsunieto {removed} wpisow. items_checked: {report.items_checked}/{report.items_total}")
        print("Teraz zrestartuj raport przez UI lub API.")
    else:
        print("\nBrak wpisow do usuniecia.")
    
    s.commit()
