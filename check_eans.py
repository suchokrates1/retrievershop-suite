#!/usr/bin/env python3
import os
os.environ['FLASK_APP'] = 'magazyn.factory:create_app'

from magazyn.factory import create_app
from magazyn.db import get_session
from magazyn.models import Product, ProductSize

app = create_app()

# EAN-y z faktury
invoice_eans = {
    '6976128181232': 'Pas samochodowy dla psa Truelove Premium czarny',
    '6971818794709': 'Szelki z odpinanym przodem dla psa Truelove Front Line Premium czarne - XL',
    '6971818794679': 'Szelki z odpinanym przodem dla psa Truelove Front Line Premium czarne - S',
    '6971818795102': 'Szelki dla psa Truelove Front Line Premium brązowe - XL',
    '6971818794822': 'Szelki dla psa Truelove Front Line Premium różowe - S',
    '6971818795133': 'Profesjonalne szelki dla psa Truelove Front Line Premium czerwone - M',
    '6971818795126': 'Profesjonalne szelki dla psa Truelove Front Line Premium czerwone - S',
    '6971818794747': 'Szelki guard dla psa Truelove Front Line Premium pomarańczowe - L',
    '6971818794723': 'Szelki guard dla psa Truelove Front Line Premium pomarańczowe - S',
    '6971818795188': 'Szelki dla psa Truelove Tropical turkusowe - M',
    '6970117170207': 'Szelki guard dla psa Truelove Front Line czarne - XL',
    '6970117170184': 'Szelki guard dla psa Truelove Front Line czarne - M',
    '6970117170641': 'Szelki dla psa Active - XL, czarny',
    '6970117170634': 'Szelki dla psa Active - L, czarny',
    '6970117170627': 'Szelki dla psa Active - M, czarny',
    '6971273110694': 'Szelki dla psa Outdoor - 2XL, czerwony',
    '6970117178500': 'Szelki easy walk dla psa Truelove Front Line brązowe - XL',
    '6970117178494': 'Szelki easy walk dla psa Truelove Front Line brązowe - L',
    '6970117178487': 'Szelki easy walk dla psa Truelove Front Line brązowe - M',
}

with app.app_context():
    with get_session() as session:
        print('Sprawdzam EAN-y z faktury w bazie danych:')
        print('='*120)
        
        found_count = 0
        missing_count = 0
        
        for ean, description in invoice_eans.items():
            # Szukam w ProductSize
            size = session.query(ProductSize).filter(ProductSize.barcode == ean).first()
            
            if size:
                product = size.product
                print(f'✓ {ean} | {product.name[:40]:40s} | {size.size:10s}')
                found_count += 1
            else:
                print(f'✗ {ean} | NIE ZNALEZIONO | {description[:50]}')
                missing_count += 1
        
        print('='*120)
        print(f'Znaleziono: {found_count}, Brakuje: {missing_count}')
