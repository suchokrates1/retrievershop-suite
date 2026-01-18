#!/usr/bin/env python3
"""
Skrypt do importu cen zakupu z Excela i porownania stanow magazynowych.

Uzycie:
    python scripts/import_excel_prices.py --compare     # tylko porownanie stanow
    python scripts/import_excel_prices.py --import      # import cen jako partie zakupu
    python scripts/import_excel_prices.py --fix-stock   # napraw stany magazynowe
"""

import argparse
import sys
from pathlib import Path
from datetime import date
from decimal import Decimal

import pandas as pd

# Dodaj sciezke do modulu magazyn
sys.path.insert(0, str(Path(__file__).parent.parent))

from magazyn.db import configure_engine, SessionLocal
from magazyn.models import Product, ProductSize, PurchaseBatch


# === MAPOWANIA ===

MODEL_TO_SERIES = {
    'Amortyzator dla średniego psa Truelove': ('Amortyzator', 'Premium'),
    'Smycz Truelove Active': ('Smycz', 'Active'),
    'Pas samochodowy Truelove': ('Pas samochodowy', 'Premium'),
    'Pas do biegania Truelove Trek Go': ('Pas trekkingowy', 'Trek Go'),
    'Szelki Truelove Active': ('Szelki', 'Active'),
    'Szelki Truelove Adventure Dog': ('Szelki', 'Adventure Dog'),
    'Szelki Truelove Blossom Premium': ('Szelki', 'Blossom'),
    'Szelki Truelove Front Line': ('Szelki', 'Front Line'),
    'Szelki Truelove Front Line Premium': ('Szelki', 'Front Line Premium'),
    'Szelki Truelove Front line Premium': ('Szelki', 'Front Line Premium'),  # literowka
    'Szelki Front Line Premium': ('Szelki', 'Front Line Premium'),  # brak Truelove
    'Szelki Truelove Front Line Premium Cordura': ('Szelki', 'Front Line Premium Cordura'),
    'Szelki Truelove Lumen': ('Szelki', 'Lumen'),
    'Szelki Truelove Lumen Lite': ('Szelki', 'Lumen Lite'),
    'Szelki Truelove Lumen Litte': ('Szelki', 'Lumen Lite'),  # literowka Litte -> Lite
    'Szelki Truelove Outdoor': ('Szelki', 'Outdoor'),
    'Szelki Truelove Tropical': ('Szelki', 'Tropical'),
    'Szelki dla psa Truelove Safe Hiking': ('Szelki', 'Safe Hiking'),
    'Szelki dla psa Truerlove Security': ('Szelki', 'Security'),  # literowka Truerlove
    'Szelki dla psa Truelove Tracker': ('Szelki', 'Tracker'),
}

COLOR_MAP = {
    'czarny': 'Czarny',
    'Czarny': 'Czarny',
    'czarne': 'Czarne',
    'Czarne': 'Czarne',
    'Czerwony': 'Czerwony',
    'czerwony': 'Czerwony',
    'Czerwone': 'Czerwone',
    'czerwone': 'Czerwone',
    'Granatowy': 'Granatowy',
    'granatowy': 'Granatowy',
    'Granatowo-biały': 'Granatowy',
    'Czerwono-biały': 'Czerwony',
    'Pomarańczowy': 'Pomarańczowy',
    'pomarańczowy': 'Pomarańczowy',
    'Pomarańczowe': 'Pomarańczowe',
    'pomarańczowe': 'Pomarańczowe',
    'Różowy': 'Różowy',
    'różowy': 'Różowy',
    'Fioletowy': 'Fioletowy',
    'fioletowy': 'Fioletowy',
    'Fioletowe': 'Fioletowy',
    'Niebieski': 'Niebieski',
    'niebieski': 'Niebieski',
    'Niebieskie': 'Niebieski',
    'Błękitny': 'Błękitny',
    'błękitny': 'Błękitny',
    'Szary': 'Szary',
    'szary': 'Szary',
    'Zielony': 'Zielony',
    'zielony': 'Zielony',
    'Srebrny': 'Srebrny',
    'srebrny': 'Srebrny',
    'Turkusowy': 'Turkusowy',
    'turkusowy': 'Turkusowy',
    'Brązowy': 'Brązowy',
    'brązowy': 'Brązowy',
    'Żółty': 'Żółty',
    'żółty': 'Żółty',
    'Limonkowy': 'Limonkowy',
}

SIZE_MAP = {
    'XS': 'XS',
    'S': 'S',
    'M': 'M',
    'L': 'L',
    'XL': 'XL',
    'XK': 'XL',  # literowka w Excelu
    '2XL': '2XL',
    'Uniwersalny': 'Uniwersalny',
}


def load_excel_data(excel_path: str):
    """Wczytaj dane z arkusza Styczen 2026."""
    xls = pd.ExcelFile(excel_path)
    df = pd.read_excel(xls, sheet_name='Styczeń 2026')
    
    excel_data = []
    for idx, row in df.iterrows():
        model = str(row['Model']).strip() if pd.notna(row['Model']) else ''
        kolor = str(row['Kolor']).strip() if pd.notna(row['Kolor']) else ''
        rozmiar = str(row['Rozmiar']).strip() if pd.notna(row['Rozmiar']) else ''
        ilosc = int(row['Ustalona liczba sztuk']) if pd.notna(row['Ustalona liczba sztuk']) else 0
        cena = float(row['Cena jedn.w zł']) if pd.notna(row['Cena jedn.w zł']) else 0.0
        
        if model not in MODEL_TO_SERIES:
            print(f"  [WARN] Nieznany model: {model}")
            continue
        
        kategoria, seria = MODEL_TO_SERIES[model]
        kolor_norm = COLOR_MAP.get(kolor, kolor)
        rozmiar_norm = SIZE_MAP.get(rozmiar, rozmiar)
        
        excel_data.append({
            'model_excel': model,
            'kategoria': kategoria,
            'seria': seria,
            'kolor': kolor_norm,
            'rozmiar': rozmiar_norm,
            'ilosc': ilosc,
            'cena': cena,
        })
    
    return excel_data


def get_db_products(session):
    """Pobierz produkty z bazy i stworz slownik do szybkiego wyszukiwania."""
    products = session.query(Product).all()
    
    # Slownik: (kategoria, seria, kolor) -> Product
    product_map = {}
    for p in products:
        key = (p.category, p.series, p.color)
        product_map[key] = p
    
    return product_map


def get_db_sizes(session):
    """Pobierz rozmiary z bazy i stworz slownik."""
    sizes = session.query(ProductSize).all()
    
    # Slownik: (product_id, size) -> ProductSize
    size_map = {}
    for s in sizes:
        key = (s.product_id, s.size)
        if key in size_map:
            # Duplikat - zsumuj ilosci
            size_map[key].quantity += s.quantity
        else:
            size_map[key] = s
    
    return size_map


def normalize_color(color):
    """Normalizuj kolor do porownania."""
    # Usun polskie znaki i zamien na lowercase
    replacements = {
        'ą': 'a', 'ć': 'c', 'ę': 'e', 'ł': 'l', 'ń': 'n',
        'ó': 'o', 'ś': 's', 'ź': 'z', 'ż': 'z',
        'Ą': 'A', 'Ć': 'C', 'Ę': 'E', 'Ł': 'L', 'Ń': 'N',
        'Ó': 'O', 'Ś': 'S', 'Ź': 'Z', 'Ż': 'Z',
    }
    result = color
    for old, new in replacements.items():
        result = result.replace(old, new)
    return result.lower()


def find_product(product_map, kategoria, seria, kolor):
    """Znajdz produkt w bazie, probujac rozne warianty koloru."""
    # Probuj dokladne dopasowanie
    key = (kategoria, seria, kolor)
    if key in product_map:
        return product_map[key]
    
    # Probuj z normalizacja koloru
    kolor_norm = normalize_color(kolor)
    for (kat, ser, col), product in product_map.items():
        if kat == kategoria and ser == seria:
            if normalize_color(col) == kolor_norm:
                return product
    
    # Probuj warianty (Czarny vs Czarne, Pomaranczowy vs Pomaranczowe)
    color_variants = {
        'Czarny': ['Czarne', 'czarny', 'czarne'],
        'Czarne': ['Czarny', 'czarny', 'czarne'],
        'Pomarańczowy': ['Pomarańczowe', 'pomarańczowy', 'pomarańczowe'],
        'Pomarańczowe': ['Pomarańczowy', 'pomarańczowy', 'pomarańczowe'],
        'Czerwony': ['Czerwone', 'czerwony', 'czerwone'],
        'Czerwone': ['Czerwony', 'czerwony', 'czerwone'],
        'Żółty': ['Żółte', 'żółty', 'żółte'],
        'Żółte': ['Żółty', 'żółty', 'żółte'],
    }
    
    if kolor in color_variants:
        for variant in color_variants[kolor]:
            key = (kategoria, seria, variant)
            if key in product_map:
                return product_map[key]
    
    # Specjalne mapowania kolorow
    special_color_map = {
        'Żółty': ['Limonkowy', 'Limonkowe', 'Żółte'],
        'Żółte': ['Limonkowy', 'Limonkowe', 'Żółty'],
        'Brązowy': ['Brązowe', 'Brązowy'],
        'Brązowe': ['Brązowy', 'Brązowe'],
    }
    
    if kolor in special_color_map:
        for variant in special_color_map[kolor]:
            key = (kategoria, seria, variant)
            if key in product_map:
                return product_map[key]
    
    return None


def compare_stocks(excel_data, session):
    """Porownaj stany magazynowe z Excela z baza danych."""
    product_map = get_db_products(session)
    size_map = get_db_sizes(session)
    
    differences = []
    matched = []
    not_found = []
    
    for item in excel_data:
        product = find_product(product_map, item['kategoria'], item['seria'], item['kolor'])
        
        if not product:
            not_found.append(item)
            continue
        
        # Znajdz rozmiar
        size_key = (product.id, item['rozmiar'])
        product_size = size_map.get(size_key)
        
        if not product_size:
            # Rozmiar nie istnieje w bazie
            not_found.append({**item, 'product_id': product.id, 'reason': 'brak rozmiaru'})
            continue
        
        excel_qty = item['ilosc']
        db_qty = product_size.quantity
        
        matched.append({
            'product': product,
            'product_size': product_size,
            'excel_item': item,
            'excel_qty': excel_qty,
            'db_qty': db_qty,
        })
        
        if excel_qty != db_qty:
            differences.append({
                'product': product,
                'product_size': product_size,
                'excel_item': item,
                'excel_qty': excel_qty,
                'db_qty': db_qty,
                'diff': excel_qty - db_qty,
            })
    
    return matched, differences, not_found


def print_comparison_report(matched, differences, not_found):
    """Wyswietl raport porownania."""
    print("\n" + "=" * 80)
    print("RAPORT POROWNANIA STANOW MAGAZYNOWYCH")
    print("Excel (Styczen 2026) vs Baza danych")
    print("=" * 80)
    
    print(f"\nDopasowano: {len(matched)} pozycji")
    print(f"Roznice w stanach: {len(differences)} pozycji")
    print(f"Nie znaleziono w bazie: {len(not_found)} pozycji")
    
    if differences:
        print("\n" + "-" * 80)
        print("ROZNICE W STANACH MAGAZYNOWYCH:")
        print("-" * 80)
        print(f"{'Produkt':<50} {'Rozmiar':<8} {'Excel':<8} {'Baza':<8} {'Roznica':<8}")
        print("-" * 80)
        
        total_diff = 0
        for d in sorted(differences, key=lambda x: (x['product'].series, x['product'].color, x['excel_item']['rozmiar'])):
            name = f"{d['product'].series} {d['product'].color}"
            size = d['excel_item']['rozmiar']
            excel = d['excel_qty']
            db = d['db_qty']
            diff = d['diff']
            total_diff += diff
            
            sign = "+" if diff > 0 else ""
            print(f"{name:<50} {size:<8} {excel:<8} {db:<8} {sign}{diff:<8}")
        
        print("-" * 80)
        sign = "+" if total_diff > 0 else ""
        print(f"{'SUMA':<50} {'':<8} {'':<8} {'':<8} {sign}{total_diff}")
    
    if not_found:
        print("\n" + "-" * 80)
        print("NIE ZNALEZIONO W BAZIE:")
        print("-" * 80)
        for item in not_found:
            reason = item.get('reason', 'brak produktu')
            print(f"  {item['seria']} {item['kolor']} {item['rozmiar']}: {item['ilosc']} szt. ({reason})")
    
    print("\n" + "=" * 80)


def import_purchase_batches(matched, session, dry_run=True):
    """Importuj partie zakupu z cenami.
    
    WAZNE: Uzywamy ilosci z BAZY (db_qty), nie z Excela!
    Partie zakupu maja odzwierciedlac aktualny stan magazynowy z przypisana cena.
    """
    print("\n" + "=" * 80)
    print("IMPORT PARTII ZAKUPU")
    print("=" * 80)
    
    today = date.today().isoformat()
    batches_to_create = []
    
    for m in matched:
        if m['excel_item']['cena'] <= 0:
            continue
        # Uzywamy ilosci z BAZY, nie z Excela
        db_qty = m['db_qty']
        if db_qty <= 0:
            continue
        
        batch = PurchaseBatch(
            product_id=m['product'].id,
            size=m['excel_item']['rozmiar'],
            quantity=db_qty,  # Ilosc z bazy
            remaining_quantity=db_qty,  # Ilosc z bazy
            price=Decimal(str(m['excel_item']['cena'])),
            purchase_date=today,
            invoice_number='IMPORT_EXCEL_2026_01',
            supplier='Import z Excela',
            notes=f"Import ze sredniej cen z ostatnich dostaw. Model Excel: {m['excel_item']['model_excel']}",
        )
        batches_to_create.append((batch, m))
    
    print(f"\nPartii do utworzenia: {len(batches_to_create)}")
    print("\nPrzykladowe partie:")
    for batch, m in batches_to_create[:10]:
        name = f"{m['product'].series} {m['product'].color}"
        print(f"  {name:<40} {batch.size:<8} {batch.quantity} szt. @ {batch.price:.2f} zl")
    
    if len(batches_to_create) > 10:
        print(f"  ... i {len(batches_to_create) - 10} wiecej")
    
    total_value = sum(float(b.price) * b.quantity for b, _ in batches_to_create)
    print(f"\nLaczna wartosc importu: {total_value:.2f} zl")
    
    if dry_run:
        print("\n[DRY RUN] Partie nie zostaly zapisane. Uzyj --import aby zapisac.")
    else:
        for batch, _ in batches_to_create:
            session.add(batch)
        session.commit()
        print(f"\nZapisano {len(batches_to_create)} partii zakupu.")
    
    return batches_to_create


def fix_stock_levels(differences, session, dry_run=True):
    """Napraw stany magazynowe na podstawie Excela."""
    print("\n" + "=" * 80)
    print("NAPRAWA STANOW MAGAZYNOWYCH")
    print("=" * 80)
    
    if not differences:
        print("\nBrak roznic do naprawy.")
        return
    
    print(f"\nPozycji do zaktualizowania: {len(differences)}")
    
    for d in differences:
        name = f"{d['product'].series} {d['product'].color}"
        size = d['excel_item']['rozmiar']
        old_qty = d['db_qty']
        new_qty = d['excel_qty']
        
        print(f"  {name:<40} {size:<8}: {old_qty} -> {new_qty}")
        
        if not dry_run:
            d['product_size'].quantity = new_qty
    
    if dry_run:
        print("\n[DRY RUN] Stany nie zostaly zmienione. Uzyj --fix-stock aby zapisac.")
    else:
        session.commit()
        print(f"\nZaktualizowano {len(differences)} stanow magazynowych.")


def main():
    parser = argparse.ArgumentParser(description='Import cen zakupu z Excela')
    parser.add_argument('--excel', default=r'c:\Users\sucho\Downloads\Stan magazynowy.xlsx',
                        help='Sciezka do pliku Excel')
    parser.add_argument('--db', default='/app/database.db',
                        help='Sciezka do bazy danych')
    parser.add_argument('--compare', action='store_true',
                        help='Tylko porownaj stany (bez zapisu)')
    parser.add_argument('--import', dest='do_import', action='store_true',
                        help='Importuj partie zakupu z cenami')
    parser.add_argument('--fix-stock', action='store_true',
                        help='Napraw stany magazynowe')
    
    args = parser.parse_args()
    
    # Konfiguruj baze danych
    configure_engine(args.db)
    from magazyn import db
    session = db.SessionLocal()
    
    try:
        # Wczytaj dane z Excela
        print("Wczytywanie danych z Excela...")
        excel_data = load_excel_data(args.excel)
        print(f"Wczytano {len(excel_data)} pozycji")
        
        # Porownaj stany
        matched, differences, not_found = compare_stocks(excel_data, session)
        print_comparison_report(matched, differences, not_found)
        
        # Import partii zakupu
        if args.do_import:
            import_purchase_batches(matched, session, dry_run=False)
        elif args.compare:
            import_purchase_batches(matched, session, dry_run=True)
        
        # Naprawa stanow
        if args.fix_stock:
            fix_stock_levels(differences, session, dry_run=False)
        elif args.compare and differences:
            fix_stock_levels(differences, session, dry_run=True)
    
    finally:
        session.close()


if __name__ == '__main__':
    main()
