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
        # Ostatni raport
        report = s.query(PriceReport).order_by(PriceReport.id.desc()).first()
        print(f"Ostatni raport: #{report.id}, status={report.status}, "
              f"total={report.items_total}, checked={report.items_checked}, "
              f"created={report.created_at}, completed={report.completed_at}")
        
        # Wszystkie itemy w raporcie
        items = s.query(PriceReportItem).filter(
            PriceReportItem.report_id == report.id
        ).all()
        
        # Klasyfikacja
        inna_ok = [i for i in items if not i.is_cheapest and i.competitor_price is None and i.error is None]
        checked_ok = [i for i in items if i.competitor_price is not None or i.is_cheapest]
        errors = [i for i in items if i.error is not None]
        
        print(f"\nRaport #{report.id} pozycje: {len(items)}")
        print(f"  Sprawdzone normalnie: {len(checked_ok)}")
        print(f"  Inna OK: {len(inna_ok)}")
        print(f"  Bledy: {len(errors)}")
        
        # Aktywne oferty
        active_offers = s.query(AllegroOffer).filter(
            AllegroOffer.publication_status == "ACTIVE"
        ).all()
        
        checked_ids = set(i.offer_id for i in items)
        unchecked = [o for o in active_offers if o.offer_id not in checked_ids]
        
        print(f"\nAktywne oferty: {len(active_offers)}")
        print(f"W raporcie: {len(checked_ids)}")
        print(f"Niesprawdzone: {len(unchecked)}")
        
        # Grupuj po product_size_id
        ps_groups = {}
        for o in active_offers:
            ps_groups.setdefault(o.product_size_id, []).append(o)
        
        # Produkty z dokladnie 1 aktywna oferta per product_size_id
        single_offer_ps = {ps_id: offs for ps_id, offs in ps_groups.items() if len(offs) == 1}
        multi_offer_ps = {ps_id: offs for ps_id, offs in ps_groups.items() if len(offs) > 1}
        
        print(f"\nProduct_size_id z 1 oferta: {len(single_offer_ps)}")
        print(f"Product_size_id z 2+ ofertami: {len(multi_offer_ps)}")
        
        # Sprawdz ktore single-offer sa niesprawdzone
        single_unchecked = []
        single_inna_ok = []
        for ps_id, offs in single_offer_ps.items():
            o = offs[0]
            if o.offer_id not in checked_ids:
                single_unchecked.append(o)
            else:
                # Sprawdz czy jest "Inna OK"
                item = next((i for i in inna_ok if i.offer_id == o.offer_id), None)
                if item:
                    single_inna_ok.append((o, item))
        
        print(f"\nSingle-offer niesprawdzone: {len(single_unchecked)}")
        print(f"Single-offer oznaczone 'Inna OK' (BLAD!): {len(single_inna_ok)}")
        
        if single_inna_ok:
            print("\nSingle-offer blednie oznaczone 'Inna OK':")
            for o, item in single_inna_ok[:20]:
                print(f"  offer_id={o.offer_id}, product_id={o.product_id}, "
                      f"ps_id={o.product_size_id}, price={o.price}, title={o.title[:50] if o.title else '?'}")
        
        # Sprawdz niesprawdzone single-offer
        if single_unchecked:
            print(f"\nSingle-offer niesprawdzone (pierwsze 10):")
            for o in single_unchecked[:10]:
                print(f"  offer_id={o.offer_id}, product_id={o.product_id}, "
                      f"ps_id={o.product_size_id}, price={o.price}")
        
        # Grupuj po product_id
        product_groups = {}
        for o in active_offers:
            product_groups.setdefault(o.product_id, []).append(o)
        
        single_product = {pid: offs for pid, offs in product_groups.items() if len(offs) == 1}
        
        print(f"\nProdukty z 1 aktywna oferta (product_id): {len(single_product)}")
        
        # Ile z nich niesprawdzonych
        sp_unchecked = []
        sp_inna_ok = []
        for pid, offs in single_product.items():
            o = offs[0]
            if o.offer_id not in checked_ids:
                sp_unchecked.append(o)
            else:
                item = next((i for i in inna_ok if i.offer_id == o.offer_id), None)
                if item:
                    sp_inna_ok.append((o, item))
        
        print(f"  Niesprawdzone: {len(sp_unchecked)}")
        print(f"  Oznaczone 'Inna OK' (BLAD!): {len(sp_inna_ok)}")
        
        if sp_inna_ok:
            print("\nProdukty z 1 oferta blednie oznaczone 'Inna OK':")
            for o, item in sp_inna_ok[:20]:
                print(f"  offer_id={o.offer_id}, product_id={o.product_id}, "
                      f"ps_id={o.product_size_id}, price={o.price}, "
                      f"title={o.title[:50] if o.title else '?'}")
        
        # Pokaz Product 54 szczegolowo
        print("\n--- PRODUKT 54 ---")
        p54_offers = s.query(AllegroOffer).filter(
            AllegroOffer.product_id == 54,
            AllegroOffer.publication_status == "ACTIVE"
        ).all()
        print(f"Aktywne oferty: {len(p54_offers)}")
        for o in p54_offers:
            in_report = o.offer_id in checked_ids
            item = next((i for i in items if i.offer_id == o.offer_id), None)
            status = "brak"
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
