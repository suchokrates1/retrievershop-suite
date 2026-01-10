#!/usr/bin/env python3
from magazyn.models import Product, ProductSize
from magazyn.db import get_session
from magazyn.factory import create_app

app = create_app()
with app.app_context():
    with get_session() as db:
        # Szukaj produktow po nazwie
        names = [
            'Pas do biegania',
            'Amortyzator',
            'Blossom',
            'Front Line Premium',
            'Smycz tradycyjna',
        ]
        
        for name in names:
            products = db.query(Product).filter(Product.name.ilike(f'%{name}%')).all()
            print(f'\n=== {name} ===')
            for p in products:
                sizes = db.query(ProductSize).filter(ProductSize.product_id == p.id).all()
                print(f'{p.name} {p.color}:')
                for s in sizes:
                    print(f'  {s.size}: barcode={s.barcode or "BRAK"}')
