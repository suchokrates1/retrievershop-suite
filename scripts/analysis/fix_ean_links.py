#!/usr/bin/env python3
from magazyn.models import AllegroOffer, ProductSize
from magazyn.db import get_session
from magazyn.factory import create_app

app = create_app()
with app.app_context():
    with get_session() as db:
        offers = db.query(AllegroOffer).filter(AllegroOffer.ean.isnot(None), AllegroOffer.product_size_id.is_(None)).all()
        print(f'Oferty z EAN bez powiazania: {len(offers)}')
        
        matched = 0
        for o in offers:
            ps = db.query(ProductSize).filter(ProductSize.barcode == o.ean).first()
            if ps:
                o.product_size_id = ps.id
                o.product_id = ps.product_id
                matched += 1
                print(f'Polaczono: {o.offer_id} ({o.ean}) -> ps.id={ps.id}')
        
        db.commit()
        print(f'Zaktualizowano: {matched}')
