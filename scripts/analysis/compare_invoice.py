#!/usr/bin/env python3
"""
Porównanie faktury PDF z bazą danych
"""
import re
from collections import defaultdict

# Produkty z faktury FS 2026/01/000328 (data: 2026-01-08)
invoice_products = [
    {
        'lp': 1,
        'name': 'Pas samochodowy dla psa Truelove Premium czarny',
        'size': None,  # Brak wariantu
        'ean': '6976128181232',
        'quantity': 6,
        'price': 52.14
    },
    {
        'lp': 2,
        'name': 'Szelki z odpinanym przodem dla psa Truelove Front Line Premium czarne',
        'size': 'XL',
        'ean': '6971818794709',
        'quantity': 4,
        'price': 131.34
    },
    {
        'lp': 3,
        'name': 'Szelki z odpinanym przodem dla psa Truelove Front Line Premium czarne',
        'size': 'S',
        'ean': '6971818794679',
        'quantity': 2,
        'price': 131.34
    },
    {
        'lp': 4,
        'name': 'Szelki dla psa Truelove Front Line Premium brązowe',
        'size': 'XL',
        'ean': '6971818795102',
        'quantity': 4,
        'price': 131.34
    },
    {
        'lp': 5,
        'name': 'Szelki dla psa Truelove Front Line Premium różowe',
        'size': 'S',
        'ean': '6971818794822',
        'quantity': 2,
        'price': 131.34
    },
    {
        'lp': 6,
        'name': 'Profesjonalne szelki dla psa Truelove Front Line Premium czerwone',
        'size': 'M',
        'ean': '6971818795133',
        'quantity': 3,
        'price': 131.34
    },
    {
        'lp': 7,
        'name': 'Profesjonalne szelki dla psa Truelove Front Line Premium czerwone',
        'size': 'S',
        'ean': '6971818795126',
        'quantity': 2,
        'price': 131.34
    },
    {
        'lp': 8,
        'name': 'Szelki guard dla psa Truelove Front Line Premium pomarańczowe',
        'size': 'L',
        'ean': '6971818794747',
        'quantity': 5,
        'price': 131.34
    },
    {
        'lp': 9,
        'name': 'Szelki guard dla psa Truelove Front Line Premium pomarańczowe',
        'size': 'S',
        'ean': '6971818794723',
        'quantity': 2,
        'price': 131.34
    },
    {
        'lp': 10,
        'name': 'Szelki dla psa Truelove Tropical turkusowe',
        'size': 'M',
        'ean': '6971818795188',
        'quantity': 2,
        'price': 131.34
    },
    {
        'lp': 11,
        'name': 'Szelki guard dla psa Truelove Front Line czarne',
        'size': 'XL',
        'ean': '6970117170207',
        'quantity': 3,
        'price': 118.14
    },
    {
        'lp': 12,
        'name': 'Szelki guard dla psa Truelove Front Line czarne',
        'size': 'M',
        'ean': '6970117170184',
        'quantity': 2,
        'price': 118.14
    },
    {
        'lp': 13,
        'name': 'Szelki dla psa Active',
        'size': 'XL, czarny',
        'ean': '6970117170641',
        'quantity': 1,
        'price': 58.08
    },
    {
        'lp': 14,
        'name': 'Szelki dla psa Active',
        'size': 'L, czarny',
        'ean': '6970117170634',
        'quantity': 1,
        'price': 58.08
    },
    {
        'lp': 15,
        'name': 'Szelki dla psa Active',
        'size': 'M, czarny',
        'ean': '6970117170627',
        'quantity': 1,
        'price': 58.08
    },
    {
        'lp': 16,
        'name': 'Szelki dla psa Outdoor',
        'size': '2XL, czerwony',
        'ean': '6971273110694',
        'quantity': 1,
        'price': 104.94
    },
    {
        'lp': 17,
        'name': 'Szelki easy walk dla psa Truelove Front Line brązowe',
        'size': 'XL',
        'ean': '6970117178500',
        'quantity': 2,
        'price': 118.14
    },
    {
        'lp': 18,
        'name': 'Szelki easy walk dla psa Truelove Front Line brązowe',
        'size': 'L',
        'ean': '6970117178494',
        'quantity': 2,
        'price': 118.14
    },
    {
        'lp': 19,
        'name': 'Szelki easy walk dla psa Truelove Front Line brązowe',
        'size': 'M',
        'ean': '6970117178487',
        'quantity': 2,
        'price': 118.14
    },
]

print("=" * 120)
print("ANALIZA FAKTURY vs BAZA DANYCH")
print("Faktura: FS 2026/01/000328")
print("Data: 2026-01-08")
print("=" * 120)
print()

print("Produkty z faktury (z EANami):")
print("=" * 120)
for p in invoice_products:
    size_str = f" ({p['size']})" if p['size'] else ""
    print(f"{p['lp']:2d}. {p['name']}{size_str}")
    print(f"    EAN: {p['ean']}")
    print(f"    Ilość: {p['quantity']}, Cena: {p['price']} zł")
    print()

print()
print("=" * 120)
print("INSTRUKCJE DO SPRAWDZENIA W BAZIE DANYCH:")
print("=" * 120)
print()
print("1. Sprawdź każdy EAN z faktury czy istnieje w tabeli product_sizes")
print("2. Sprawdź czy rozmiar się zgadza")
print("3. Sprawdź czy nazwa produktu się zgadza")
print()
print("Komendy SQL do wykonania na RPI:")
print()

for p in invoice_products:
    print(f"-- Produkt {p['lp']}: {p['name']}")
    print(f"SELECT p.name, ps.size, ps.barcode, ps.stock")
    print(f"FROM product_sizes ps")
    print(f"JOIN products p ON p.id = ps.product_id")
    print(f"WHERE ps.barcode = '{p['ean']}';")
    print()
