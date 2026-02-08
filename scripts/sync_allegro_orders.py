"""Skrypt do synchronizacji zamowien z Allegro API."""
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
    skipped = 0

    with get_session() as db:
        for cf in checkout_forms:
            try:
                order_data = parse_allegro_order_to_data(cf)
                cf_id = cf.get("id", "")
                existing = db.query(Order).filter(
                    or_(
                        Order.external_order_id == cf_id,
                        Order.order_id == "allegro_{}".format(cf_id),
                    )
                ).first()
                if existing:
                    if not existing.user_login and order_data.get("user_login"):
                        existing.user_login = order_data["user_login"]
                    if not existing.email and order_data.get("email"):
                        existing.email = order_data["email"]
                    if not existing.phone and order_data.get("phone"):
                        existing.phone = order_data["phone"]
                    if not existing.external_order_id:
                        existing.external_order_id = cf_id
                    updated += 1
                else:
                    sync_order_from_data(db, order_data)
                    internal_status = get_allegro_internal_status(order_data)
                    add_order_status(
                        db, order_data["order_id"], internal_status,
                        notes="Sync z Allegro API"
                    )
                    synced += 1
            except Exception as exc:
                import traceback
                cf_id_str = cf.get("id", "?")
                print("Blad przy {}: {}".format(cf_id_str, exc))
                traceback.print_exc()
                skipped += 1
                if skipped <= 3:
                    # Pokaz pelny traceback dla pierwszych bledow
                    pass
                elif skipped == 4:
                    print("... kolejne bledy ukryte ...")
        db.commit()

    print("Wynik: {} nowych, {} zaktualizowanych, {} pominieto".format(
        synced, updated, skipped
    ))
