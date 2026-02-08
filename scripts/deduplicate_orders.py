"""
Skrypt deduplikacji zamowien.

Problem: zamowienia zsynchronizowane zarowno przez BaseLinker API jak i Allegro API
maja rozne order_id ale ten sam external_order_id (UUID Allegro).

Rozwiazanie: usuwamy duplikaty z BaseLinkera (zachowujemy Allegro API, bo maja
lepsze dopasowanie produktow do magazynu).
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from magazyn.factory import create_app
from magazyn.db import get_session
from magazyn.models import Order, OrderProduct, OrderStatusLog

app = create_app()

with app.app_context():
    with get_session() as db:
        # Znajdz BaseLinker zamowienia, ktore maja duplikat w Allegro API
        bl_orders = db.query(Order).filter(~Order.order_id.like('allegro_%')).all()
        al_ext_ids = set(
            r.external_order_id for r in
            db.query(Order.external_order_id).filter(Order.order_id.like('allegro_%')).all()
        )

        to_delete = []
        for order in bl_orders:
            if order.external_order_id in al_ext_ids:
                to_delete.append(order)

        print("Duplikaty do usuniecia (BaseLinker z odpowiednikiem Allegro API): {}".format(len(to_delete)))

        if not to_delete:
            print("Brak duplikatow - baza czysta.")
            sys.exit(0)

        # Usun powiazane rekordy i zamowienia
        deleted_products = 0
        deleted_statuses = 0
        deleted_orders = 0

        for order in to_delete:
            oid = order.order_id
            # Usun produkty zamowienia
            dp = db.query(OrderProduct).filter(OrderProduct.order_id == oid).delete()
            deleted_products += dp
            # Usun logi statusow
            ds = db.query(OrderStatusLog).filter(OrderStatusLog.order_id == oid).delete()
            deleted_statuses += ds
            # Usun zamowienie
            db.delete(order)
            deleted_orders += 1

        db.commit()

        remaining = db.query(Order).count()
        print("Usunieto: {} zamowien, {} produktow, {} statusow".format(
            deleted_orders, deleted_products, deleted_statuses))
        print("Pozostalo zamowien w bazie: {}".format(remaining))
