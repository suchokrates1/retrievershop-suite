#!/usr/bin/env python3
"""Analiza brakujacych EAN w magazynie"""
from magazyn.models import AllegroOffer, ProductSize, Product
from magazyn.db import get_session
from magazyn.factory import create_app

app = create_app()
with app.app_context():
    with get_session() as db:
        # Oferty z EAN ale bez powiazania
        offers = db.query(AllegroOffer).filter(
            AllegroOffer.ean.isnot(None), 
            AllegroOffer.product_size_id.is_(None)
        ).all()
        
        print(f'Oferty z EAN bez powiazania: {len(offers)}\n')
        print('='*80)
        
        for o in offers:
            print(f'\nAllegro: {o.title}')
            print(f'  EAN: {o.ean}')
            
            # Szukaj produktu w magazynie po nazwie
            words = o.title.lower().split()
            
            # Szukaj produktow ktore zawieraja kluczowe slowa
            matching_products = []
            for product in db.query(Product).all():
                product_name_lower = product.name.lower()
                # Sprawdz czy nazwa produktu zawiera kluczowe slowa z tytulu
                if 'amortyzator' in o.title.lower() and 'amortyzator' in product_name_lower:
                    matching_products.append(product)
                elif 'blossom' in o.title.lower() and 'blossom' in product_name_lower:
                    matching_products.append(product)
                elif 'front line' in o.title.lower() and 'front line' in product_name_lower:
                    matching_products.append(product)
                elif 'pas do biegania' in o.title.lower() and 'pas' in product_name_lower and 'biegania' in product_name_lower:
                    matching_products.append(product)
                elif 'smycz' in o.title.lower() and 'smycz' in product_name_lower:
                    matching_products.append(product)
            
            if matching_products:
                print(f'  Potencjalne produkty w magazynie:')
                for p in matching_products[:5]:  # Max 5
                    # Sprawdz kolory
                    color_match = ''
                    title_lower = o.title.lower()
                    product_name_lower = p.name.lower()
                    
                    colors = ['czarny', 'czerwony', 'niebieski', 'granatowy', 'zielony', 
                              'pomarańczowy', 'żółty', 'różowy', 'fioletowy', 'szary', 'brązowy',
                              'biały']
                    for color in colors:
                        if color in title_lower and color in product_name_lower:
                            color_match = f' (kolor: {color})'
                            break
                    
                    print(f'    - {p.name}{color_match}')
                    # Pokaz rozmiary bez barcode
                    sizes_without_barcode = []
                    for ps in p.sizes:
                        if not ps.barcode or ps.barcode.strip() == '':
                            sizes_without_barcode.append(ps.size)
                    if sizes_without_barcode:
                        print(f'      Rozmiary BEZ barcode: {", ".join(sizes_without_barcode)}')
            else:
                print(f'  BRAK PRODUKTU W MAGAZYNIE')
