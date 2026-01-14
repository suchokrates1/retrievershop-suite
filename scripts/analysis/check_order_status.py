#!/usr/bin/env python3
"""Check order status in database and BaseLinker."""

import os
import sys
import json
import requests
from datetime import datetime

# Add magazyn to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'magazyn'))

from magazyn.db import init_db, get_session
from magazyn.models import Order, OrderStatusLog
from magazyn.config import settings
from sqlalchemy import desc

def check_order_status(order_identifier):
    """Check order status in database and BaseLinker."""
    
    # Don't init_db, just use get_session
    # init_db()
    
    # Query local database
    with get_session() as db:
        order = db.query(Order).filter(
            (Order.order_id == order_identifier) |
            (Order.external_order_id == order_identifier) |
            (Order.shop_order_id == order_identifier)
        ).first()
        
        if not order:
            print(f"❌ Zamówienie {order_identifier} nie znalezione w bazie danych")
            return
        
        print(f"\n📦 Zamówienie w NASZEJ BAZIE:")
        print(f"   Order ID: {order.order_id}")
        print(f"   External ID: {order.external_order_id}")
        print(f"   Shop Order ID: {order.shop_order_id}")
        print(f"   Date: {datetime.fromtimestamp(order.date_add) if order.date_add else 'N/A'}")
        print(f"   Customer: {order.customer_name}")
        print(f"   Amount: {order.payment_done} {order.currency}")
        
        # Get latest status from log
        status_log = db.query(OrderStatusLog).filter(
            OrderStatusLog.order_id == order.order_id
        ).order_by(desc(OrderStatusLog.timestamp)).first()
        
        if status_log:
            print(f"\n   ✅ Status: {status_log.status}")
            print(f"   ⏰ Timestamp: {status_log.timestamp}")
        else:
            print(f"\n   ⚠️  Brak statusu w logu")
        
        # Get all status history
        all_statuses = db.query(OrderStatusLog).filter(
            OrderStatusLog.order_id == order.order_id
        ).order_by(OrderStatusLog.timestamp).all()
        
        if all_statuses:
            print(f"\n   📋 Historia statusów ({len(all_statuses)}):")
            for s in all_statuses:
                print(f"      • {s.timestamp} → {s.status}")
    
    # Query BaseLinker
    print(f"\n📡 Sprawdzam w BASELINKER...")
    try:
        api_url = "https://api.baselinker.com/connector.php"
        headers = {"X-BLToken": settings.API_TOKEN}
        
        params = {
            "method": "getOrders",
            "parameters": json.dumps({
                "order_id": int(order.order_id)
            })
        }
        
        response = requests.post(api_url, headers=headers, data=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        if data.get("status") != "SUCCESS":
            print(f"❌ BaseLinker API error: {data.get('error_message', 'Unknown error')}")
            return
            
        orders = data.get("orders", [])
        
        if orders:
            bl_order = orders[0]
            print(f"\n✅ Zamówienie w BASELINKER:")
            print(f"   Order ID: {bl_order.get('order_id')}")
            print(f"   Status ID: {bl_order.get('order_status_id')}")
            print(f"   Status: {bl_order.get('order_status')}")
            print(f"   Date: {datetime.fromtimestamp(bl_order.get('date_add', 0))}")
            
            # Map BaseLinker status
            status_map = {
                91615: "pobrano (Nowe zamówienie)",
                91616: "niewydrukowano (Oczekujące)",
                91617: "wydrukowano (W realizacji)",
                91618: "spakowano (Gotowe do wysyłki)",
                91619: "w_drodze (Wysłane)",
                91620: "w_drodze (W transporcie)",
                91621: "dostarczono (Zakończone)",
                91622: "anulowano (Anulowane)",
                91623: "zwrot (Zwrot)",
            }
            
            bl_status_id = bl_order.get('order_status_id')
            mapped_status = status_map.get(bl_status_id, f"nieznany ({bl_status_id})")
            
            print(f"\n   🔄 Mapowany status: {mapped_status}")
            
            # Compare
            if status_log:
                if mapped_status.startswith(status_log.status):
                    print(f"\n✅ STATUSY SIĘ ZGADZAJĄ!")
                else:
                    print(f"\n⚠️  NIEZGODNOŚĆ STATUSÓW!")
                    print(f"   Nasza baza: {status_log.status}")
                    print(f"   BaseLinker: {mapped_status}")
        else:
            print(f"❌ Nie znaleziono zamówienia w BaseLinker")
            
    except Exception as e:
        print(f"❌ Błąd podczas pobierania z BaseLinker: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python check_order_status.py <order_id>")
        sys.exit(1)
    
    order_id = sys.argv[1]
    check_order_status(order_id)
