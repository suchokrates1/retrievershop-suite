#!/usr/bin/env python3
"""
Sprawdzenie historii statusów zamówienia
"""

import sys
sys.path.insert(0, '/app')

from magazyn.factory import create_app
from magazyn.models import Order, OrderStatusLog, OrderProduct
from magazyn.db import SessionLocal

app = create_app()

ORDER_ID = "28685136"

with app.app_context():
    db = SessionLocal()
    
    print("=" * 80)
    print(f"HISTORIA STATUSÓW ZAMÓWIENIA: {ORDER_ID}")
    print("=" * 80)
    
    # Pobierz zamówienie
    order = db.query(Order).filter(Order.order_id == ORDER_ID).first()
    
    if not order:
        print(f"\n❌ Zamówienie {ORDER_ID} nie istnieje w bazie danych!")
        db.close()
        sys.exit(1)
    
    # Informacje o zamówieniu
    print(f"\n📋 DANE ZAMÓWIENIA:")
    print(f"  Order ID: {order.order_id}")
    print(f"  External Order ID: {order.external_order_id or 'BRAK'}")
    print(f"  Data zamówienia: {order.date_add}")
    print(f"  Kupujący: {order.user_login or order.customer_name}")
    print(f"  Platforma: {order.platform or 'BRAK'}")
    print(f"  Status ID: {order.order_status_id}")
    print(f"  Numer śledzenia: {order.delivery_package_nr or 'BRAK'}")
    print(f"  Kod kuriera: {order.courier_code or 'BRAK'}")
    print(f"  Data potwierdzenia: {order.date_confirmed or 'BRAK'}")
    print(f"  Metoda dostawy: {order.delivery_method or 'BRAK'}")
    
    # Produkty w zamówieniu
    print(f"\n📦 PRODUKTY:")
    order_products = db.query(OrderProduct).filter(
        OrderProduct.order_id == ORDER_ID
    ).all()
    
    if order_products:
        for op in order_products:
            print(f"  - {op.name} (x{op.quantity}) - {op.price_brutto} PLN")
            if op.ean:
                print(f"    EAN: {op.ean}")
            if op.sku:
                print(f"    SKU: {op.sku}")
    else:
        print("  Brak produktów")
    
    # Historia statusów
    print(f"\n📊 HISTORIA STATUSÓW:")
    status_logs = db.query(OrderStatusLog).filter(
        OrderStatusLog.order_id == ORDER_ID
    ).order_by(OrderStatusLog.timestamp.asc()).all()
    
    if not status_logs:
        print("  ⚠️  BRAK HISTORII STATUSÓW!")
        print("  To może być problem - zamówienie powinno mieć przynajmniej jeden wpis w historii")
    else:
        for i, log in enumerate(status_logs, 1):
            print(f"\n  {i}. Status: {log.status}")
            print(f"     Data: {log.timestamp}")
            if log.tracking_number:
                print(f"     Numer śledzenia: {log.tracking_number}")
            if log.courier_code:
                print(f"     Kurier: {log.courier_code}")
            if log.notes:
                print(f"     Notatki: {log.notes}")
    
    # Analiza problemów
    print(f"\n" + "=" * 80)
    print("ANALIZA PROBLEMÓW:")
    print("=" * 80)
    
    problems = []
    
    # Problem 1: Brak historii statusów
    if not status_logs:
        problems.append("❌ Zamówienie nie ma żadnej historii statusów")
    
    # Problem 2: Tracking number ale brak daty
    if order.delivery_package_nr and not order.date_confirmed:
        problems.append(f"⚠️  Istnieje numer śledzenia ale brak daty potwierdzenia")
    
    # Problem 3: Duplikaty w historii
    if status_logs:
        status_counts = {}
        for log in status_logs:
            key = (log.status, log.tracking_number)
            status_counts[key] = status_counts.get(key, 0) + 1
        
        for key, count in status_counts.items():
            if count > 1:
                status, tracking = key
                problems.append(f"⚠️  Duplikat statusu: '{status}' (tracking: {tracking}) pojawia się {count} razy")
    
    if problems:
        for problem in problems:
            print(f"\n{problem}")
    else:
        print("\n✅ Nie znaleziono problemów")
    
    db.close()
    
    print("\n" + "=" * 80)
