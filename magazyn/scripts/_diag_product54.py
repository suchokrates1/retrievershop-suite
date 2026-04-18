"""Diagnostyka produktu 54 - dlaczego nie jest sprawdzany w raporcie cenowym."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from magazyn.factory import create_app
from magazyn.db import get_session
from magazyn.models import AllegroOffer, PriceReportItem, PriceReport
from sqlalchemy import text

app = create_app()
with app.app_context():
    with get_session() as s:
        # Product 54
        p = s.execute(text('SELECT id, name FROM products WHERE id = 54')).fetchone()
        print(f"Produkt: {p}")
        
        # Oferty Allegro dla product_id=54
        offers = s.query(AllegroOffer).filter(AllegroOffer.product_id == 54).all()
        print(f"\nOferty Allegro (product_id=54): {len(offers)}")
        for o in offers:
            print(f"  offer_id={o.offer_id}, status={o.publication_status}, "
                  f"price={o.price}, ps_id={o.product_size_id}")
        
        # Sprawdz ostatni raport
        report = s.query(PriceReport).order_by(PriceReport.id.desc()).first()
        if report:
            print(f"\nOstatni raport: #{report.id}, status={report.status}, "
                  f"total={report.items_total}, checked={report.items_checked}")
            
            # Czy oferty produktu 54 sa w raporcie?
            offer_ids = [o.offer_id for o in offers]
            items = s.query(PriceReportItem).filter(
                PriceReportItem.report_id == report.id,
                PriceReportItem.offer_id.in_(offer_ids)
            ).all()
            print(f"Pozycje w raporcie #{report.id}: {len(items)}")
            for it in items:
                print(f"  offer_id={it.offer_id}, is_cheapest={it.is_cheapest}, "
                      f"our_price={it.our_price}, competitor={it.competitor_price}, "
                      f"error={it.error}")
            
            # Ile ACTIVE ofert nie jest w raporcie?
            all_active = s.query(AllegroOffer).filter(
                AllegroOffer.publication_status == "ACTIVE"
            ).count()
            
            checked_ids = set(
                r[0] for r in s.query(PriceReportItem.offer_id).filter(
                    PriceReportItem.report_id == report.id
                ).all()
            )
            
            active_offers = s.query(AllegroOffer).filter(
                AllegroOffer.publication_status == "ACTIVE"
            ).all()
            
            unchecked = [o for o in active_offers if o.offer_id not in checked_ids]
            print(f"\nAktywne oferty: {all_active}")
            print(f"Sprawdzone w raporcie: {len(checked_ids)}")
            print(f"Niesprawdzone: {len(unchecked)}")
            
            # Pokaz niesprawdzone
            if unchecked:
                print("\nNiesprawdzone oferty:")
                for o in unchecked[:20]:
                    print(f"  offer_id={o.offer_id}, product_id={o.product_id}, "
                          f"ps_id={o.product_size_id}, price={o.price}")
            
            # Sprawdz product_size_id tych niesprawdzonych
            unchecked_ps_ids = set(o.product_size_id for o in unchecked if o.product_size_id)
            print(f"\nNiesprawdzone - unikalne product_size_id: {len(unchecked_ps_ids)}")
            
            # Czy niesprawdzone maja siostry wg product_size_id?
            for o in unchecked[:10]:
                siblings = s.query(AllegroOffer).filter(
                    AllegroOffer.product_size_id == o.product_size_id,
                    AllegroOffer.publication_status == "ACTIVE"
                ).all()
                print(f"  offer={o.offer_id} ps_id={o.product_size_id}: "
                      f"{len(siblings)} aktywnych ofert z tym ps_id")
