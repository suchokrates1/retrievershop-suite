#!/usr/bin/env python3
"""Uzupelnia barcody w magazynie na podstawie EAN z Allegro - wersja 2"""
from magazyn.models import AllegroOffer, ProductSize, Product
from magazyn.db import get_session
from magazyn.factory import create_app

# Mapowanie kolorow z Allegro na nazwy w magazynie
COLOR_MAP = {
    'czarny': 'Czarny',
    'czerwony': 'Czerwony', 
    'czerwone': 'Czerwony',  # lub Czerwono-biały dla Blossom
    'niebieski': 'Niebieski',
    'granatowy': 'Granatowy',
    'granatowe': 'Granatowy',
    'granatowa': 'Granatowy',
    'zielony': 'Zielony',
    'pomarańczowy': 'Pomarańczowy',
    'żółty': 'Żółty',
    'różowy': 'Różowy',
    'fioletowy': 'Fioletowy',
    'szary': 'Szary',
    'brązowy': 'Brązowy',
}

# Mapowanie rozmiarow
SIZE_MAP = {
    'xs': 'XS',
    's': 'S', 
    'm': 'M',
    'l': 'L',
    'xl': 'XL',
    '2xl': '2XL',
    'xxl': '2XL',
}

def extract_color(title):
    """Wyciaga kolor z tytulu"""
    title_lower = title.lower()
    for allegro_color, db_color in COLOR_MAP.items():
        if allegro_color in title_lower:
            return db_color
    return None

def extract_size(title):
    """Wyciaga rozmiar z tytulu"""
    title_lower = title.lower()
    for allegro_size, db_size in SIZE_MAP.items():
        words = title_lower.split()
        for word in words:
            if word == allegro_size:
                return db_size
    return None

app = create_app()
with app.app_context():
    with get_session() as db:
        # Oferty z EAN ale bez powiazania
        offers = db.query(AllegroOffer).filter(
            AllegroOffer.ean.isnot(None), 
            AllegroOffer.product_size_id.is_(None)
        ).all()
        
        print(f'Oferty z EAN bez powiazania: {len(offers)}\n')
        
        updated = 0
        for o in offers:
            color = extract_color(o.title)
            size = extract_size(o.title)
            
            print(f'\nAllegro: {o.title}')
            print(f'  EAN: {o.ean}, Kolor: {color}, Rozmiar: {size}')
            
            if not color or not size:
                print(f'  POMIN - nie mozna wyciagnac koloru lub rozmiaru')
                continue
            
            # Znajdz odpowiedni produkt po typie i kolorze
            product_type = None
            title_lower = o.title.lower()
            
            if 'amortyzator' in title_lower:
                product_type = 'Amortyzator'
            elif 'blossom' in title_lower:
                product_type = 'Blossom'
            elif 'front line' in title_lower:
                product_type = 'Front Line Premium'
            
            if not product_type:
                print(f'  POMIN - nieznany typ produktu')
                continue
            
            # Szukaj produktu po nazwie i polu color
            products = db.query(Product).filter(
                Product.name.contains(product_type),
                Product.color == color
            ).all()
            
            if not products:
                # Dla Blossom czerwone -> Czerwono-bialy
                if product_type == 'Blossom' and color == 'Czerwony':
                    products = db.query(Product).filter(
                        Product.name.contains(product_type),
                        Product.color == 'Czerwono-biały'
                    ).all()
            
            if not products:
                print(f'  BRAK produktu {product_type} kolor={color} w magazynie')
                continue
            
            print(f'  Znaleziono {len(products)} produktow')
                
            for product in products:
                # Znajdz rozmiar
                ps = db.query(ProductSize).filter(
                    ProductSize.product_id == product.id,
                    ProductSize.size == size
                ).first()
                
                if ps:
                    if not ps.barcode or ps.barcode.strip() == '':
                        # Uzupelnij barcode
                        print(f'  UZUPELNIAM: {product.name} ({product.color}) rozmiar {size} <- EAN {o.ean}')
                        ps.barcode = o.ean
                        db.commit()
                        updated += 1
                        
                        # Teraz polacz oferte z produktem
                        o.product_size_id = ps.id
                        o.product_id = ps.product_id
                        db.commit()
                        print(f'  POWIAZANO oferte {o.offer_id} z ProductSize {ps.id}')
                        break
                    else:
                        # Barcode juz jest - sprawdz czy inny
                        if ps.barcode != o.ean:
                            print(f'  UWAGA: {product.name} {size} ma inny barcode: {ps.barcode} (Allegro: {o.ean})')
                            # Dodaj nowy barcode do oferty (EAN z Allegro) bez zmiany magazynu
                            # Ale polacz z tym samym ProductSize
                            o.product_size_id = ps.id
                            o.product_id = ps.product_id
                            db.commit()
                            print(f'  POWIAZANO oferte {o.offer_id} z istniejacym ProductSize {ps.id} (rozne EAN)')
                            updated += 1
                            break
                        else:
                            print(f'  JUZ MATCHUJE: {product.name} {size}')
        
        print(f'\nZaktualizowano: {updated}')
