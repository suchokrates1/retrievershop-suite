#!/usr/bin/env python3
"""
Sprawdzenie EANów z faktury w bazie danych przez SSH
"""
import subprocess
import json

invoice_products = [
    {'lp': 1, 'name': 'Pas samochodowy dla psa Truelove Premium czarny', 'size': None, 'ean': '6976128181232', 'quantity': 6},
    {'lp': 2, 'name': 'Szelki z odpinanym przodem dla psa Truelove Front Line Premium czarne', 'size': 'XL', 'ean': '6971818794709', 'quantity': 4},
    {'lp': 3, 'name': 'Szelki z odpinanym przodem dla psa Truelove Front Line Premium czarne', 'size': 'S', 'ean': '6971818794679', 'quantity': 2},
    {'lp': 4, 'name': 'Szelki dla psa Truelove Front Line Premium brązowe', 'size': 'XL', 'ean': '6971818795102', 'quantity': 4},
    {'lp': 5, 'name': 'Szelki dla psa Truelove Front Line Premium różowe', 'size': 'S', 'ean': '6971818794822', 'quantity': 2},
    {'lp': 6, 'name': 'Profesjonalne szelki dla psa Truelove Front Line Premium czerwone', 'size': 'M', 'ean': '6971818795133', 'quantity': 3},
    {'lp': 7, 'name': 'Profesjonalne szelki dla psa Truelove Front Line Premium czerwone', 'size': 'S', 'ean': '6971818795126', 'quantity': 2},
    {'lp': 8, 'name': 'Szelki guard dla psa Truelove Front Line Premium pomarańczowe', 'size': 'L', 'ean': '6971818794747', 'quantity': 5},
    {'lp': 9, 'name': 'Szelki guard dla psa Truelove Front Line Premium pomarańczowe', 'size': 'S', 'ean': '6971818794723', 'quantity': 2},
    {'lp': 10, 'name': 'Szelki dla psa Truelove Tropical turkusowe', 'size': 'M', 'ean': '6971818795188', 'quantity': 2},
    {'lp': 11, 'name': 'Szelki guard dla psa Truelove Front Line czarne', 'size': 'XL', 'ean': '6970117170207', 'quantity': 3},
    {'lp': 12, 'name': 'Szelki guard dla psa Truelove Front Line czarne', 'size': 'M', 'ean': '6970117170184', 'quantity': 2},
    {'lp': 13, 'name': 'Szelki dla psa Active', 'size': 'XL', 'ean': '6970117170641', 'quantity': 1},
    {'lp': 14, 'name': 'Szelki dla psa Active', 'size': 'L', 'ean': '6970117170634', 'quantity': 1},
    {'lp': 15, 'name': 'Szelki dla psa Active', 'size': 'M', 'ean': '6970117170627', 'quantity': 1},
    {'lp': 16, 'name': 'Szelki dla psa Outdoor', 'size': '2XL', 'ean': '6971273110694', 'quantity': 1},
    {'lp': 17, 'name': 'Szelki easy walk dla psa Truelove Front Line brązowe', 'size': 'XL', 'ean': '6970117178500', 'quantity': 2},
    {'lp': 18, 'name': 'Szelki easy walk dla psa Truelove Front Line brązowe', 'size': 'L', 'ean': '6970117178494', 'quantity': 2},
    {'lp': 19, 'name': 'Szelki easy walk dla psa Truelove Front Line brązowe', 'size': 'M', 'ean': '6970117178487', 'quantity': 2},
]

print("=" * 140)
print("PORÓWNANIE FAKTURY Z BAZĄ DANYCH - SZCZEGÓŁOWA ANALIZA")
print("=" * 140)
print()

problems = []
ok_count = 0

for product in invoice_products:
    print(f"\n{product['lp']:2d}. {product['name']}")
    if product['size']:
        print(f"    Rozmiar z faktury: {product['size']}")
    print(f"    EAN z faktury: {product['ean']}")
    print(f"    Ilość zamówiona: {product['quantity']}")
    
    # Sprawdź w bazie
    ean = product['ean']
    
    try:
        cmd = f'''ssh rpi "cd retrievershop-suite && docker compose exec -T magazyn_app python -c \\"from magazyn.db import SessionLocal; from magazyn.models import Product, ProductSize; session = SessionLocal(); ps = session.query(ProductSize).filter_by(barcode='{ean}').first(); p = session.query(Product).filter_by(id=ps.product_id).first() if ps else None; print(p.name + '|' + ps.size + '|' + ps.barcode + '|' + str(ps.stock) + '|' + str(p.id) + '|' + str(ps.id) if ps and p else 'NOT_FOUND'); session.close()\\""'''
        
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=10
        )
        
        output = result.stdout.strip()
        
        if output and output != 'NOT_FOUND' and '|' in output:
            parts = output.split('|')
            db_name = parts[0]
            db_size = parts[1]
            db_barcode = parts[2]
            db_stock = parts[3]
            product_id = parts[4]
            size_id = parts[5]
            
            print(f"    ✓ Znaleziono w bazie:")
            print(f"      - Nazwa w bazie: {db_name}")
            print(f"      - Rozmiar w bazie: {db_size}")
            print(f"      - EAN w bazie: {db_barcode}")
            print(f"      - Stan magazynowy: {db_stock}")
            print(f"      - Product ID: {product_id}, Size ID: {size_id}")
            
            # Sprawdź zgodność
            issues = []
            if product['size'] and db_size != product['size']:
                issues.append(f"NIEZGODNOŚĆ ROZMIARU! Faktura: {product['size']}, Baza: {db_size}")
            if db_barcode != product['ean']:
                issues.append(f"NIEZGODNOŚĆ EAN! Faktura: {product['ean']}, Baza: {db_barcode}")
            
            if issues:
                print(f"    ⚠️  PROBLEMY:")
                for issue in issues:
                    print(f"      - {issue}")
                problems.append({
                    'lp': product['lp'],
                    'name': product['name'],
                    'issues': issues
                })
            else:
                print(f"    ✓ Wszystko OK")
                ok_count += 1
        else:
            print(f"    ✗ NIE ZNALEZIONO W BAZIE!")
            print(f"      EAN {product['ean']} nie istnieje w tabeli product_sizes")
            problems.append({
                'lp': product['lp'],
                'name': product['name'],
                'issues': ['Produkt nie istnieje w bazie - brak EAN']
            })
    except Exception as e:
        print(f"    ✗ BŁĄD podczas sprawdzania: {e}")
        problems.append({
            'lp': product['lp'],
            'name': product['name'],
            'issues': [f'Błąd zapytania: {str(e)}']
        })

print("\n")
print("=" * 140)
print("PODSUMOWANIE")
print("=" * 140)
print(f"Sprawdzono produktów: {len(invoice_products)}")
print(f"OK: {ok_count}")
print(f"Problemy: {len(problems)}")
print()

if problems:
    print("LISTA PROBLEMÓW:")
    print("-" * 140)
    for p in problems:
        print(f"{p['lp']:2d}. {p['name']}")
        for issue in p['issues']:
            print(f"    - {issue}")
        print()
