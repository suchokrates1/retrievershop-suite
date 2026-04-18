"""Diagnostyka raportow cenowych - oferty z 1 aukcja."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from magazyn.factory import create_app
from magazyn.db import get_session
from magazyn.models import AllegroOffer, PriceReportItem, PriceReport
from sqlalchemy import text
from collections import Counter

app = create_app()
with app.app_context():
    with get_session() as s:
        # Wszystkie raporty
        reports = s.query(PriceReport).order_by(PriceReport.id.desc()).limit(5).all()
        print("=== RAPORTY ===")
        for r in reports:
            print(f"  #{r.id}: status={r.status}, total={r.items_total}, "
                  f"checked={r.items_checked}, created={r.created_at}")
        
        # Znajdz ostatni ZAKONCZONY raport
        completed = s.query(PriceReport).filter(
            PriceReport.status.in_(["completed", "completed_with_errors"])
        ).order_by(PriceReport.id.desc()).first()
        
        if completed:
            print(f"\n=== OSTATNI UKONCZONY RAPORT #{completed.id} ===")
            items = s.query(PriceReportItem).filter(
                PriceReportItem.report_id == completed.id
            ).all()
            
            inna_ok = [i for i in items if not i.is_cheapest and i.competitor_price is None and i.error is None]
            checked_ok = [i for i in items if i.competitor_price is not None or (i.is_cheapest and i.error is None)]
            errors = [i for i in items if i.error is not None]
            
            print(f"Pozycje: {len(items)}")
            print(f"  Sprawdzone normalnie: {len(checked_ok)}")
            print(f"  Inna OK: {len(inna_ok)}")
            print(f"  Bledy: {len(errors)}")
            
            # Aktywne oferty w momencie raportu
            active_offers = s.query(AllegroOffer).filter(
                AllegroOffer.publication_status == "ACTIVE"
            ).all()
            
            checked_ids = set(i.offer_id for i in items)
            missing = [o for o in active_offers if o.offer_id not in checked_ids]
            
            print(f"\nAktywne oferty teraz: {len(active_offers)}")
            print(f"W raporcie: {len(checked_ids)}")
            print(f"BRAKUJACE w raporcie: {len(missing)}")
            
            if missing:
                print("\nBrakujace oferty (nie ma ich w raporcie!):")
                for o in missing[:30]:
                    print(f"  offer_id={o.offer_id}, product_id={o.product_id}, "
                          f"ps_id={o.product_size_id}, price={o.price}, "
                          f"title={o.title[:50] if o.title else '?'}")
            
            # Grupuj aktywne po product_size_id
            ps_groups = {}
            for o in active_offers:
                ps_groups.setdefault(o.product_size_id, []).append(o)
            
            single_ps = {ps_id: offs for ps_id, offs in ps_groups.items() if len(offs) == 1}
            
            # Ktore single-offer sa "Inna OK" - to jest blad
            print(f"\n--- ANALIZA 'INNA OK' ---")
            print(f"Inna OK oferty: {len(inna_ok)}")
            
            for item in inna_ok:
                # Sprawdz ile aktywnych ofert ma ten sam product_size_id
                offer = next((o for o in active_offers if o.offer_id == item.offer_id), None)
                if offer:
                    ps_id = offer.product_size_id
                    group_size = len(ps_groups.get(ps_id, []))
                    if group_size == 1:
                        print(f"  !! BLAD: {item.offer_id} (ps_id={ps_id}) = jedyna "
                              f"oferta dla tego ps_id, ale oznaczona Inna OK! "
                              f"price={item.our_price}, product_id={offer.product_id}")
        else:
            print("\nBrak ukonczonych raportow - sprawdzam biezacy")
        
        # Raport biezacy (#41)
        current = s.query(PriceReport).order_by(PriceReport.id.desc()).first()
        print(f"\n=== BIEZACY RAPORT #{current.id} ===")
        items = s.query(PriceReportItem).filter(
            PriceReportItem.report_id == current.id
        ).all()
        
        inna_ok = [i for i in items if not i.is_cheapest and i.competitor_price is None and i.error is None]
        
        active_offers = s.query(AllegroOffer).filter(
            AllegroOffer.publication_status == "ACTIVE"
        ).all()
        
        ps_groups = {}
        for o in active_offers:
            ps_groups.setdefault(o.product_size_id, []).append(o)
        
        print(f"'Inna OK' z 1 oferta na ps_id (BLEDNE):")
        bledne = 0
        for item in inna_ok:
            offer = next((o for o in active_offers if o.offer_id == item.offer_id), None)
            if offer:
                ps_id = offer.product_size_id
                group_size = len(ps_groups.get(ps_id, []))
                if group_size == 1:
                    bledne += 1
                    print(f"  offer_id={item.offer_id}, ps_id={ps_id}, "
                          f"price={item.our_price}, product_id={offer.product_id}, "
                          f"title={offer.title[:50] if offer.title else '?'}")
        print(f"Lacznie blednych: {bledne}")
        
        # Pokaz Product 54
        print(f"\n--- PRODUKT 54 ---")
        p54 = s.query(AllegroOffer).filter(
            AllegroOffer.product_id == 54,
            AllegroOffer.publication_status == "ACTIVE"
        ).all()
        print(f"Aktywne oferty: {len(p54)}")
        for o in p54:
            item = next((i for i in items if i.offer_id == o.offer_id), None)
            status = "brak w raporcie"
            if item:
                if item.error:
                    status = f"BLAD: {item.error}"
                elif item.competitor_price is None and not item.is_cheapest:
                    status = "Inna OK"
                elif item.is_cheapest:
                    status = f"Najtanszy (vs {item.competitor_price})"
                else:
                    status = f"Drozszy (vs {item.competitor_price})"
            print(f"  {o.offer_id} ps_id={o.product_size_id} cena={o.price} -> {status}")
