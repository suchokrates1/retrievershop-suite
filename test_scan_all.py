#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test skanowania wszystkich EAN-ów z faktury 2026-01-08
"""
import sys
sys.path.insert(0, '/app')

from magazyn.factory import create_app
from magazyn.domain.products import find_by_barcode

app = create_app()

# Wszystkie EAN-y z faktury
test_eans = [
    ('6976128181232', 'Pas samochodowy'),
    ('6971818794709', 'Front Line Premium czarne XL'),
    ('6971818794679', 'Front Line Premium czarne S'),
    ('6971818795102', 'Front Line Premium brązowe XL'),
    ('6971818794822', 'Front Line Premium różowe XS'),
    ('6971818795133', 'Front Line Premium czerwone M'),
    ('6971818795126', 'Front Line Premium czerwone S'),
    ('6971818794747', 'Front Line Premium pomarańczowe L'),
    ('6971818794723', 'Front Line Premium pomarańczowe S'),
    ('6971818795188', 'Tropical turkusowe M'),
    ('6970117170207', 'Front Line czarne XL'),
    ('6970117170184', 'Front Line czarne M'),
    ('6970117170641', 'Active czarny XL'),
    ('6970117170634', 'Active czarny L'),
    ('6970117170627', 'Active czarny M'),
    ('6971273110694', 'Outdoor czerwony 2XL'),
    ('6970117178500', 'easy walk brązowe XL'),
    ('6970117178494', 'easy walk brązowe L'),
    ('6970117178487', 'easy walk brązowe M'),
]

with app.app_context():
    print("\n" + "=" * 120)
    print("TEST SKANOWANIA - wszystkie EAN-y z faktury 2026-01-08")
    print("=" * 120)
    print()
    
    success = 0
    failed = 0
    
    for ean, description in test_eans:
        result = find_by_barcode(ean)
        
        if result:
            product_name = result['name']
            color = result.get('color', '')
            size_name = result['size']
            product_size_id = result['product_size_id']
            
            full_name = f"{product_name} {color}" if color else product_name
            
            print(f"✓ {ean} | {description:35s} | "
                  f"{full_name[:35]:35s} | "
                  f"Rozmiar: {size_name:5s} | "
                  f"PS_ID: {product_size_id}")
            success += 1
        else:
            print(f"✗ {ean} | {description:35s} | NIE ZNALEZIONO!")
            failed += 1
    
    print("\n" + "=" * 120)
    print(f"WYNIK: Sukces={success}/19, Błędy={failed}/19")
    print("=" * 120)
    
    if failed == 0:
        print("\n🎉 WSZYSTKIE EAN-Y DZIAŁAJĄ POPRAWNIE! System skanowania jest w pełni funkcjonalny.")
    else:
        print(f"\n⚠️  UWAGA: {failed} EAN-ów nie zostało znalezionych. Sprawdź błędy powyżej.")
