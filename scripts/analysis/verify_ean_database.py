#!/usr/bin/env python3
"""
Weryfikacja i naprawa bazy danych EAN
1. Sprawdzenie produktów Cordura (ID 76, 77)
2. Weryfikacja długości wszystkich EAN-ów (8 lub 13 cyfr)
3. Dodanie brakujących serii
"""

import sys
sys.path.insert(0, '/app')

from magazyn.factory import create_app
from magazyn.models import Product, ProductSize
from magazyn.db import SessionLocal

def check_ean_validity(ean):
    """Sprawdza czy EAN ma poprawną długość (8 lub 13 cyfr)"""
    if not ean:
        return False, "Brak EAN"
    
    ean_str = str(ean).strip()
    
    if not ean_str.isdigit():
        return False, f"EAN zawiera niedozwolone znaki: {ean_str}"
    
    length = len(ean_str)
    if length == 8:
        return True, "EAN-8 OK"
    elif length == 13:
        return True, "EAN-13 OK"
    else:
        return False, f"Nieprawidłowa długość: {length} cyfr (wymagane 8 lub 13)"

app = create_app()

with app.app_context():
    db = SessionLocal()
    
    print("=" * 80)
    print("WERYFIKACJA BAZY DANYCH EAN")
    print("=" * 80)
    
    # 1. Sprawdzenie produktów Cordura
    print("\n" + "=" * 80)
    print("1. SPRAWDZENIE PRODUKTÓW CORDURA")
    print("=" * 80)
    
    cordura_products = {
        76: {
            "expected_series": "Front Line Premium Cordura",
            "expected_color": "Czarny",
            "expected_eans": {
                "L": "6974327885111",
                "XL": "6974327885128"
            }
        },
        77: {
            "expected_series": "Front Line Premium Cordura",
            "expected_color": "Pomarańczowy",
            "expected_eans": {
                "L": "6974327885210",
                "XL": "697432787885227"  # Ten może być błędny (15 cyfr)
            }
        }
    }
    
    for product_id, expected_data in cordura_products.items():
        print(f"\n--- Product ID {product_id} ---")
        
        product = db.query(Product).filter(Product.id == product_id).first()
        
        if not product:
            print(f"❌ BŁĄD: Produkt {product_id} nie istnieje!")
            continue
        
        print(f"Nazwa: {product.name}")
        print(f"Seria: {product.series or 'BRAK'}")
        print(f"Kolor: {product.color or 'BRAK'}")
        
        # Sprawdzenie serii
        if product.series != expected_data["expected_series"]:
            print(f"⚠️  Błędna seria! Oczekiwana: {expected_data['expected_series']}")
            print(f"   Naprawiam...")
            product.series = expected_data["expected_series"]
            db.commit()
            print(f"✅ Seria poprawiona")
        else:
            print(f"✅ Seria poprawna")
        
        # Sprawdzenie koloru
        if product.color != expected_data["expected_color"]:
            print(f"⚠️  Błędny kolor! Oczekiwany: {expected_data['expected_color']}, Obecny: {product.color}")
        else:
            print(f"✅ Kolor poprawny")
        
        # Sprawdzenie EAN-ów
        sizes = db.query(ProductSize).filter(
            ProductSize.product_id == product_id
        ).all()
        
        print(f"\nEAN-y w bazie:")
        for size in sizes:
            valid, msg = check_ean_validity(size.barcode)
            status = "✅" if valid else "❌"
            print(f"  {status} {size.size}: {size.barcode} ({msg}) - Stan: {size.quantity}")
            
            # Sprawdzenie czy EAN zgadza się z oczekiwanym
            if size.size in expected_data["expected_eans"]:
                expected_ean = expected_data["expected_eans"][size.size]
                if size.barcode != expected_ean:
                    print(f"     ⚠️  Oczekiwany EAN: {expected_ean}")
    
    # 2. Sprawdzenie wszystkich EAN-ów w bazie
    print("\n" + "=" * 80)
    print("2. WERYFIKACJA WSZYSTKICH EAN-ÓW W BAZIE")
    print("=" * 80)
    
    all_sizes = db.query(ProductSize).all()
    
    invalid_eans = []
    ean_stats = {
        "total": 0,
        "valid_8": 0,
        "valid_13": 0,
        "invalid": 0,
        "null": 0
    }
    
    for size in all_sizes:
        ean_stats["total"] += 1
        
        if not size.barcode:
            ean_stats["null"] += 1
            invalid_eans.append({
                "product_id": size.product_id,
                "size": size.size,
                "ean": None,
                "reason": "Brak EAN"
            })
            continue
        
        valid, msg = check_ean_validity(size.barcode)
        
        if valid:
            if len(str(size.barcode)) == 8:
                ean_stats["valid_8"] += 1
            else:
                ean_stats["valid_13"] += 1
        else:
            ean_stats["invalid"] += 1
            invalid_eans.append({
                "product_id": size.product_id,
                "size": size.size,
                "ean": size.barcode,
                "reason": msg
            })
    
    print(f"\n📊 STATYSTYKI:")
    print(f"  Wszystkich EAN-ów: {ean_stats['total']}")
    print(f"  ✅ Poprawnych EAN-13: {ean_stats['valid_13']}")
    print(f"  ✅ Poprawnych EAN-8: {ean_stats['valid_8']}")
    print(f"  ❌ Niepoprawnych: {ean_stats['invalid']}")
    print(f"  ⚠️  Brak EAN: {ean_stats['null']}")
    
    if invalid_eans:
        print(f"\n❌ NIEPOPRAWNE EAN-Y ({len(invalid_eans)}):")
        print("-" * 80)
        for item in invalid_eans[:20]:  # Pokaż maksymalnie 20
            product = db.query(Product).filter(Product.id == item['product_id']).first()
            product_name = product.name if product else "NIEZNANY"
            print(f"  Product ID {item['product_id']}: {product_name}")
            print(f"    Rozmiar: {item['size']}")
            print(f"    EAN: {item['ean']}")
            print(f"    Błąd: {item['reason']}")
            print()
        
        if len(invalid_eans) > 20:
            print(f"  ... i {len(invalid_eans) - 20} więcej")
    
    # 3. Produkty bez serii
    print("\n" + "=" * 80)
    print("3. PRODUKTY BEZ SERII")
    print("=" * 80)
    
    products_no_series = db.query(Product).filter(
        Product.series == None
    ).all()
    
    print(f"\nZnaleziono {len(products_no_series)} produktów bez serii:")
    
    for product in products_no_series[:10]:  # Pokaż maksymalnie 10
        print(f"\n  Product ID {product.id}: {product.name}")
        print(f"    Kategoria: {product.category}")
        print(f"    Marka: {product.brand}")
        print(f"    Kolor: {product.color}")
        
        # Pokaż EAN-y
        sizes = db.query(ProductSize).filter(
            ProductSize.product_id == product.id
        ).all()
        if sizes:
            print(f"    EAN-y:")
            for size in sizes:
                print(f"      {size.size}: {size.barcode}")
    
    if len(products_no_series) > 10:
        print(f"\n  ... i {len(products_no_series) - 10} więcej")
    
    db.close()
    
    print("\n" + "=" * 80)
    print("WERYFIKACJA ZAKOŃCZONA")
    print("=" * 80)
