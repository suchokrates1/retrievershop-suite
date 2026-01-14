#!/usr/bin/env python3
"""Analyze current product names to understand structure."""

import sys
sys.path.insert(0, '/app')

from magazyn.db import get_session
from magazyn.models import Product

with get_session() as session:
    products = session.query(Product).order_by(Product.name).all()
    
    print("=" * 80)
    print(f"WSZYSTKIE PRODUKTY ({len(products)}):")
    print("=" * 80)
    
    for p in products:
        print(f"[{p.id:3d}] {p.name:60s} | {p.color}")
    
    print("\n" + "=" * 80)
    print("UNIKALNE WZORCE:")
    print("=" * 80)
    
    categories = set()
    series = set()
    
    for p in products:
        name = p.name.lower()
        
        # Wykryj kategorię
        if 'szelki' in name:
            categories.add('Szelki')
        elif 'smycz' in name:
            categories.add('Smycz')
        elif 'pas' in name and 'bezpiecz' in name:
            categories.add('Pas bezpieczeństwa')
        elif 'obroża' in name:
            categories.add('Obroża')
        else:
            categories.add(f'INNE: {p.name}')
        
        # Wykryj serię
        if 'front line premium' in name:
            series.add('Front Line Premium')
        elif 'front line' in name:
            series.add('Front Line')
        elif 'active' in name:
            series.add('Active')
        elif 'blossom' in name:
            series.add('Blossom')
        elif 'tropical' in name:
            series.add('Tropical')
        elif 'amor' in name:
            series.add('Amor')
        elif 'classic' in name:
            series.add('Classic')
        else:
            series.add(f'INNA: {p.name}')
    
    print("\nKategorie:", sorted(categories))
    print("\nSerie:", sorted(series))
