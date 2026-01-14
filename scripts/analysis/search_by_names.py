#!/usr/bin/env python3
"""
Wyszukiwanie produktów po nazwach w bazie
"""
import subprocess
import re

# Klucze wyszukiwania z faktury
search_terms = [
    ('Pas samochodowy', 'Truelove', 'Premium', 'czarny'),
    ('Szelki', 'odpina', 'Front Line', 'Premium', 'czarne', 'XL'),
    ('Szelki', 'odpina', 'Front Line', 'Premium', 'czarne', 'S'),
    ('Szelki', 'Front Line', 'Premium', 'brązowe', 'XL'),
    ('Szelki', 'Front Line', 'Premium', 'różowe', 'S'),
    ('Szelki', 'Front Line', 'Premium', 'czerwone', 'M'),
    ('Szelki', 'Front Line', 'Premium', 'czerwone', 'S'),
    ('Szelki', 'guard', 'Front Line', 'Premium', 'pomarańczowe', 'L'),
    ('Szelki', 'guard', 'Front Line', 'Premium', 'pomarańczowe', 'S'),
    ('Szelki', 'Tropical', 'turkusowe', 'M'),
    ('Szelki', 'guard', 'Front Line', 'czarne', 'XL'),
    ('Szelki', 'guard', 'Front Line', 'czarne', 'M'),
    ('Szelki', 'Active', 'XL', 'czarny'),
    ('Szelki', 'Active', 'L', 'czarny'),
    ('Szelki', 'Active', 'M', 'czarny'),
    ('Szelki', 'Outdoor', '2XL', 'czerwony'),
    ('Szelki', 'easy walk', 'Front Line', 'brązowe', 'XL'),
    ('Szelki', 'easy walk', 'Front Line', 'brązowe', 'L'),
    ('Szelki', 'easy walk', 'Front Line', 'brązowe', 'M'),
]

print("=" * 140)
print("WYSZUKIWANIE PRODUKTÓW W BAZIE PO NAZWACH")
print("=" * 140)
print()

print("Pobieranie wszystkich produktów z bazy...")
cmd = '''ssh rpi "cd retrievershop-suite && docker compose exec -T magazyn_app python -c \\"from magazyn.db import SessionLocal; from magazyn.models import Product, ProductSize; session = SessionLocal(); products = session.query(Product).all(); for p in products: sizes = session.query(ProductSize).filter_by(product_id=p.id).all(); [print(f'{p.id}|{p.name}|{ps.size}|{ps.barcode or \\'BRAK\\'}|{ps.stock}') for ps in sizes]; session.close()\\""'''

result = subprocess.run(
    cmd,
    shell=True,
    capture_output=True,
    text=True,
    timeout=30
)

print("Analiza znalezionych produktów...")
print()

if result.returncode != 0:
    print(f"BŁĄD: {result.stderr}")
else:
    lines = result.stdout.strip().split('\n')
    products_db = []
    for line in lines:
        if '|' in line:
            parts = line.split('|')
            if len(parts) >= 5:
                products_db.append({
                    'id': parts[0],
                    'name': parts[1],
                    'size': parts[2],
                    'ean': parts[3],
                    'stock': parts[4]
                })
    
    print(f"Znaleziono {len(products_db)} rozmiarów produktów w bazie")
    print()
    
    # Szukaj podobnych produktów dla każdego z faktury
    print("=" * 140)
    print("DOPASOWYWANIE PRODUKTÓW:")
    print("=" * 140)
    
    invoice_eans = [
        '6976128181232', '6971818794709', '6971818794679', '6971818795102',
        '6971818794822', '6971818795133', '6971818795126', '6971818794747',
        '6971818794723', '6971818795188', '6970117170207', '6970117170184',
        '6970117170641', '6970117170634', '6970117170627', '6971273110694',
        '6970117178500', '6970117178494', '6970117178487'
    ]
    
    for i, (ean, terms) in enumerate(zip(invoice_eans, search_terms), 1):
        print(f"\n{i}. Szukam produktu z EAN: {ean}")
        print(f"   Słowa kluczowe: {', '.join(terms)}")
        
        matches = []
        for product in products_db:
            name_lower = product['name'].lower()
            match_count = sum(1 for term in terms if term.lower() in name_lower)
            
            if match_count >= 2:  # Minimum 2 dopasowania
                matches.append((match_count, product))
        
        if matches:
            matches.sort(reverse=True, key=lambda x: x[0])
            print(f"   Znaleziono {len(matches)} potencjalnych dopasowań:")
            for score, product in matches[:3]:  # Top 3
                print(f"     - {product['name']} ({product['size']})")
                print(f"       EAN w bazie: {product['ean']}")
                print(f"       Stan: {product['stock']}, ID: {product['id']}")
                print(f"       Dopasowanie: {score}/{len(terms)} słów")
        else:
            print(f"   ✗ Nie znaleziono podobnych produktów")
