#!/usr/bin/env python3
"""Powiaz pas do biegania i amortyzator - produkty jednorozmiarowe"""
from magazyn.models import AllegroOffer, ProductSize, Product
from magazyn.db import get_session
from magazyn.factory import create_app

app = create_app()
with app.app_context():
    with get_session() as db:
        # Pas do biegania z psem dogtrekking Truelove czarny -> Pas trekkingowy Trek Go Czarny
        offer = db.query(AllegroOffer).filter(AllegroOffer.ean == '6970117177794').first()
        if offer:
            print(f'Allegro: {offer.title}')
            print(f'  EAN: {offer.ean}')
            
            # Szukaj produktu - Pas trekkingowy Czarny
            product = db.query(Product).filter(
                Product.name.contains('Pas trekkingowy'),
                Product.color == 'Czarny'
            ).first()
            
            if product:
                print(f'  Znaleziono: {product.name} ({product.color})')
                # Szukaj rozmiaru Uniwersalny
                ps = db.query(ProductSize).filter(
                    ProductSize.product_id == product.id,
                    ProductSize.size == 'Uniwersalny'
                ).first()
                
                if ps:
                    if not ps.barcode or ps.barcode.strip() == '':
                        ps.barcode = offer.ean
                        print(f'  Uzupelniono barcode: {offer.ean}')
                    
                    offer.product_size_id = ps.id
                    offer.product_id = ps.product_id
                    db.commit()
                    print(f'  POWIAZANO z ProductSize {ps.id}')
            else:
                print('  BRAK produktu w magazynie')
        
        print()
        
        # Amortyzator do smyczy dla sredniego psa Truelove czerwony -> Amortyzator Premium Czerwony
        offer = db.query(AllegroOffer).filter(AllegroOffer.ean == '6971273110809').first()
        if offer:
            print(f'Allegro: {offer.title}')
            print(f'  EAN: {offer.ean}')
            
            # Szukaj produktu - Amortyzator Czerwony
            product = db.query(Product).filter(
                Product.name.contains('Amortyzator'),
                Product.color == 'Czerwony'
            ).first()
            
            if product:
                print(f'  Znaleziono: {product.name} ({product.color})')
                # Szukaj rozmiaru Uniwersalny
                ps = db.query(ProductSize).filter(
                    ProductSize.product_id == product.id,
                    ProductSize.size == 'Uniwersalny'
                ).first()
                
                if ps:
                    # Sprawdz czy barcode pasuje
                    if ps.barcode and ps.barcode != offer.ean:
                        print(f'  UWAGA: Inny barcode w magazynie: {ps.barcode} vs Allegro: {offer.ean}')
                    
                    offer.product_size_id = ps.id
                    offer.product_id = ps.product_id
                    db.commit()
                    print(f'  POWIAZANO z ProductSize {ps.id}')
            else:
                print('  BRAK produktu w magazynie')
        
        # Sprawdz ile zostalo
        remaining = db.query(AllegroOffer).filter(
            AllegroOffer.ean.isnot(None), 
            AllegroOffer.product_size_id.is_(None)
        ).count()
        print(f'\nPozostalo ofert z EAN bez powiazania: {remaining}')
