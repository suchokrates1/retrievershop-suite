"""Skrypt do ponownego dopasowania produktow w zamowieniach do magazynu."""
import sys
sys.path.insert(0, '/app')

from magazyn.factory import create_app

app = create_app()
with app.app_context():
    from magazyn.allegro_api.orders import (
        fetch_all_allegro_orders,
        parse_allegro_order_to_data,
        get_allegro_internal_status,
    )
    from magazyn.orders import sync_order_from_data, add_order_status
    from magazyn.db import get_session
    from magazyn.models import Order
    from sqlalchemy import or_

    print("Pobieranie zamowien z Allegro API...")
    checkout_forms = fetch_all_allegro_orders()
    print("Pobrano {} zamowien z Allegro".format(len(checkout_forms)))

    synced = 0
    updated = 0
    errors = 0

    with get_session() as db:
        for cf in checkout_forms:
            try:
                order_data = parse_allegro_order_to_data(cf)
                # Zawsze wywoluj sync_order_from_data - re-matchuje produkty
                sync_order_from_data(db, order_data)
                cf_id = cf.get("id", "")
                existing = db.query(Order).filter(
                    or_(
                        Order.external_order_id == cf_id,
                        Order.order_id == "allegro_{}".format(cf_id),
                    )
                ).first()
                if existing:
                    updated += 1
                else:
                    synced += 1
            except Exception as exc:
                import traceback
                cf_id_str = cf.get("id", "?")
                print("Blad przy {}: {}".format(cf_id_str, exc))
                traceback.print_exc()
                errors += 1
        db.commit()

    print("===== WYNIK =====")
    print("Nowych: {}".format(synced))
    print("Zaktualizowanych (re-matched): {}".format(updated))
    print("Bledow: {}".format(errors))
