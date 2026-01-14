#!/usr/bin/env python3
from magazyn.models import AllegroOffer, ProductSize
from magazyn.db import get_session
from magazyn.factory import create_app

app = create_app()
with app.app_context():
    with get_session() as db:
        offers = db.query(AllegroOffer).filter(AllegroOffer.ean.isnot(None), AllegroOffer.product_size_id.is_(None)).all()
        print(f'Oferty z EAN bez powiazania: {len(offers)}\n')
        
        for o in offers:
            ps = db.query(ProductSize).filter(ProductSize.barcode == o.ean).first()
            if ps:
                print(f'MATCH: {o.title}')
                print(f'  EAN: {o.ean} -> ProductSize {ps.id}')
            else:
                print(f'BRAK MATCHA: {o.title}')
                print(f'  EAN z Allegro: {o.ean}')
                # Szukaj podobnych
                similar = db.query(ProductSize).filter(ProductSize.barcode.like(f'%{o.ean[-6:]}%')).all()
                if similar:
                    print(f'  Podobne barcode w magazynie:')
                    for s in similar:
                        print(f'    - {s.barcode} ({s.product.name} {s.size})')
                else:
                    print(f'  Brak podobnych w magazynie')
            print()
