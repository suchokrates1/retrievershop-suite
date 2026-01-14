#!/usr/bin/env python3
from magazyn.models import AllegroOffer, ProductSize
from magazyn.db import get_session
from magazyn.factory import create_app

app = create_app()
with app.app_context():
    with get_session() as db:
        # Szukaj ofert z tym EAN
        offers = db.query(AllegroOffer).filter(AllegroOffer.ean == '6971273110694').all()
        print(f'Oferty Allegro z EAN 6971273110694: {len(offers)}')
        for o in offers:
            print(f'  Offer ID: {o.offer_id}')
            print(f'  Title: {o.title}')
            print(f'  EAN: {o.ean}')
            print(f'  product_size_id: {o.product_size_id}')
            print()
        
        # Szukaj w product_sizes
        ps = db.query(ProductSize).filter(ProductSize.barcode == '6971273110694').first()
        if ps:
            print(f'ProductSize: id={ps.id}, product={ps.product.name}, size={ps.size}, barcode={ps.barcode}')
        else:
            print('BRAK ProductSize z tym barcode')
