#!/usr/bin/env python3
"""Patch: restore today's Maria order + anti-duplicate-label guards."""
from __future__ import annotations

import json
import sys

from sqlalchemy import text

from magazyn.db import get_session
from magazyn.factory import create_app

ORDER_ID = "allegro_b94d1a60-69ae-11f1-b822-3b889f6dec5e"
CHECKOUT_ID = "b94d1a60-69ae-11f1-b822-3b889f6dec5e"
SHIPMENT_ID = "6551805c-e442-4859-9305-8a3ce5e94698"
WAYBILL = "A004TIBRF9"
PRINTED_AT = "2026-06-16T22:17:09.937681"

LAST_ORDER_DATA = {
    "order_id": ORDER_ID,
    "external_order_id": CHECKOUT_ID,
    "name": "Kamizelka chłodząca dla średniego psa Truelove",
    "size": "M",
    "color": "Żółty",
    "customer": "Maria Leśniak",
    "email": "m5scka8pk9+6131f63a9@allegromail.pl",
    "phone": "+48888515191",
    "user_login": "Client:86389410",
    "platform": "allegro",
    "confirmed": True,
    "date_add": 1781633476,
    "date_confirmed": 1781633485,
    "shipping": "Allegro One Box, One Kurier",
    "delivery_price": 0,
    "delivery_fullname": "Maria Leśniak",
    "delivery_address": "Myśliwska 66a/136",
    "delivery_city": "Kraków",
    "delivery_postcode": "30-718",
    "delivery_country_code": "PL",
    "delivery_point_id": "AL490KR1",
    "delivery_point_name": "Allegro One Box - AL490KR1",
    "delivery_point_address": "Myśliwska 51",
    "delivery_point_postcode": "30-718",
    "delivery_point_city": "Kraków",
    "currency": "PLN",
    "payment_method": "Przelew online",
    "payment_method_cod": "0",
    "payment_done": 217.0,
    "products": [
        {
            "name": "Kamizelka chłodząca dla średniego psa Truelove M żółta",
            "quantity": 1,
            "price_brutto": "217.00",
            "auction_id": "18600509805",
            "sku": "",
            "ean": "",
            "attributes": "",
        }
    ],
    "courier_code": "ALLEGRO",
    "delivery_package_module": "Allegro One Box, One Kurier",
    "delivery_package_nr": WAYBILL,
    "package_ids": [SHIPMENT_ID],
    "tracking_numbers": [WAYBILL],
}

PRODUCTS_JSON = json.dumps(
    [
        {
            "name": "Kamizelka chłodząca dla średniego psa Truelove M żółta",
            "quantity": 1,
            "price_brutto": "217.00",
            "auction_id": "18600509805",
            "sku": None,
            "ean": "",
            "variant_id": "",
            "product_id": "",
            "order_product_id": None,
            "attributes": "",
            "location": "",
        }
    ],
    ensure_ascii=False,
)


def main() -> int:
    app = create_app()
    last_data_json = json.dumps(LAST_ORDER_DATA, ensure_ascii=False)
    with app.app_context():
        with get_session() as db:
            exists = db.execute(
                text("SELECT 1 FROM orders WHERE order_id = :oid"),
                {"oid": ORDER_ID},
            ).fetchone()
            if not exists:
                db.execute(
                    text(
                        """
                        INSERT INTO orders (
                            order_id, external_order_id, customer_name, email, phone, user_login,
                            platform, confirmed, date_add, date_confirmed, delivery_method,
                            delivery_price, delivery_fullname, delivery_address, delivery_city,
                            delivery_postcode, delivery_country_code, delivery_point_id,
                            delivery_point_name, delivery_point_address, delivery_point_postcode,
                            delivery_point_city, want_invoice, currency, payment_method,
                            payment_method_cod, payment_done, courier_code, delivery_package_module,
                            delivery_package_nr, products_json, customer_token,
                            wfirma_invoice_id, wfirma_invoice_number, emails_sent,
                            real_profit_sale_price, real_profit_purchase_cost,
                            real_profit_packaging_cost, real_profit_allegro_fees,
                            real_profit_amount, real_profit_fee_source,
                            real_profit_shipping_estimated, real_profit_is_final,
                            real_profit_updated_at
                        ) VALUES (
                            :order_id, :external_order_id, :customer_name, :email, :phone, :user_login,
                            'allegro', true, 1781633476, 1781633485, 'Allegro One Box, One Kurier',
                            0.00, 'Maria Leśniak', 'Myśliwska 66a/136', 'Kraków', '30-718', 'PL',
                            'AL490KR1', 'Allegro One Box - AL490KR1', 'Myśliwska 51', '30-718', 'Kraków',
                            false, 'PLN', 'Przelew online', false, 217.00, 'ALLEGRO',
                            'Allegro One Box, One Kurier', :waybill, :products_json,
                            'CZnK0aecPJ8Y9zhO15SY_wBDZG5pWWga8SOyPqU1uWg',
                            620449269, 'FBV 354/2026', '{"confirmation": true, "invoice": true}',
                            217.00, 0.00, 0.16, 28.04, 188.80, 'api', false, true,
                            '2026-06-16 22:13:48.647214'
                        )
                        """
                    ),
                    {
                        "order_id": ORDER_ID,
                        "external_order_id": CHECKOUT_ID,
                        "customer_name": "Maria Leśniak",
                        "email": "m5scka8pk9+6131f63a9@allegromail.pl",
                        "phone": "+48888515191",
                        "user_login": "Client:86389410",
                        "waybill": WAYBILL,
                        "products_json": PRODUCTS_JSON,
                    },
                )
                print("INSERT order", ORDER_ID)
            else:
                db.execute(
                    text(
                        """
                        UPDATE orders SET
                            delivery_package_nr = :waybill,
                            courier_code = 'ALLEGRO',
                            payment_done = 217.00
                        WHERE order_id = :oid
                        """
                    ),
                    {"oid": ORDER_ID, "waybill": WAYBILL},
                )
                print("UPDATE order", ORDER_ID)

            db.execute(
                text(
                    """
                    INSERT INTO order_products (order_id, name, quantity, price_brutto, auction_id)
                    SELECT :oid, :name, 1, 217.00, '18600509805'
                    WHERE NOT EXISTS (
                        SELECT 1 FROM order_products WHERE order_id = :oid
                    )
                    """
                ),
                {
                    "oid": ORDER_ID,
                    "name": "Kamizelka chłodząca dla średniego psa Truelove M żółta",
                },
            )

            has_wydrukowano = db.execute(
                text(
                    """
                    SELECT 1 FROM order_status_logs
                    WHERE order_id = :oid AND status = 'wydrukowano'
                    LIMIT 1
                    """
                ),
                {"oid": ORDER_ID},
            ).fetchone()
            if not has_wydrukowano:
                db.execute(
                    text(
                        """
                        INSERT INTO order_status_logs
                            (order_id, status, tracking_number, courier_code, timestamp, notes)
                        VALUES
                            (:oid, 'wydrukowano', :waybill, 'ALLEGRO', :ts, 'Patch: blokada ponownego druku')
                        """
                    ),
                    {"oid": ORDER_ID, "waybill": WAYBILL, "ts": PRINTED_AT},
                )

            db.execute(
                text(
                    """
                    INSERT INTO printed_orders (order_id, printed_at, last_order_data)
                    VALUES (:oid, :printed_at, :last_data)
                    ON CONFLICT (order_id) DO UPDATE SET
                        printed_at = EXCLUDED.printed_at,
                        last_order_data = EXCLUDED.last_order_data
                    """
                ),
                {"oid": ORDER_ID, "printed_at": PRINTED_AT, "last_data": last_data_json},
            )

            db.execute(
                text(
                    """
                    INSERT INTO agent_state (key, value)
                    VALUES (:key, :value)
                    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
                    """
                ),
                {"key": f"sm_shipment:{ORDER_ID}", "value": SHIPMENT_ID},
            )

            rybarczyk = "allegro_0607cce1-6821-11f1-a3b4-27708eea4f6f"
            db.execute(
                text(
                    """
                    INSERT INTO agent_state (key, value)
                    VALUES (:key, 'df49429b-4ad2-458d-bf3c-b7b1363adb0f')
                    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
                    """
                ),
                {"key": f"sm_shipment:{rybarczyk}"},
            )

            db.commit()

    print("OK: Maria", ORDER_ID, "shipment", SHIPMENT_ID, "waybill", WAYBILL)
    print("OK: Rybarczyk sm_shipment pinned to original")
    return 0


if __name__ == "__main__":
    sys.exit(main())
