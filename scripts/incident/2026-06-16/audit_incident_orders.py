#!/usr/bin/env python3
"""Audit incident orders for duplicate invoices/emails/labels."""
from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import text

from magazyn.db import get_session
from magazyn.factory import create_app

INCIDENT_ORDER_IDS = [
    "allegro_b94d1a60-69ae-11f1-b822-3b889f6dec5e",
    "allegro_4be30940-6444-11f1-8e8a-b13312e55057",
    "allegro_d259ffa0-6454-11f1-b09e-572fb364178c",
    "allegro_9f6c6bf0-65a8-11f1-9c59-0d1dedc4969b",
    "allegro_069eb011-663c-11f1-aaa4-e763e1206a1e",
    "allegro_bf1de1b0-6641-11f1-b9ca-7f92d3ec60b8",
    "allegro_ec8a7641-675e-11f1-a3b4-27708eea4f6f",
    "allegro_6dd51200-67c3-11f1-b727-4bfd698bc7d4",
    "allegro_526fffd0-67d6-11f1-b09e-572fb364178c",
    "allegro_db9b0d20-67fb-11f1-a057-8f1ad7cb1230",
    "allegro_1002a0e0-680c-11f1-9c59-0d1dedc4969b",
    "allegro_0607cce1-6821-11f1-a3b4-27708eea4f6f",
    "allegro_8f2a7160-6828-11f1-8f37-811bbbf37ca0",
    "allegro_f2956c30-682a-11f1-a42a-ed5f40aaa868",
    "allegro_dfa0e3e0-687d-11f1-a3b1-4316fada8457",
    "allegro_543c0900-68a1-11f1-92d4-a1f19a0c7034",
    "allegro_6d830610-68a2-11f1-b9ca-7f92d3ec60b8",
]


def main() -> int:
    app = create_app()
    with app.app_context():
        with get_session() as db:
            print("=== Orders in incident set ===")
            rows = db.execute(
                text(
                    """
                    SELECT o.order_id, o.customer_name, o.delivery_package_nr,
                           o.wfirma_invoice_number, o.wfirma_invoice_id, o.emails_sent,
                           po.printed_at,
                           (SELECT value FROM agent_state WHERE key = 'sm_shipment:' || o.order_id) AS sm_shipment
                    FROM orders o
                    LEFT JOIN printed_orders po ON po.order_id = o.order_id
                    WHERE o.order_id = ANY(:ids)
                    ORDER BY o.customer_name
                    """
                ),
                {"ids": INCIDENT_ORDER_IDS},
            ).fetchall()
            for r in rows:
                print(
                    f"{r.customer_name:25} waybill={r.delivery_package_nr or '-':22} "
                    f"invoice={r.wfirma_invoice_number or '-':16} id={r.wfirma_invoice_id or '-'} "
                    f"printed={r.printed_at or '-'} sm={ (r.sm_shipment or '-')[:8]}"
                )
                if r.emails_sent:
                    try:
                        emails = json.loads(r.emails_sent) if isinstance(r.emails_sent, str) else r.emails_sent
                        print(f"  emails_sent: {emails}")
                    except Exception:
                        print(f"  emails_sent: {r.emails_sent}")

            print("\n=== Status logs since 2026-06-16 20:00 ===")
            logs = db.execute(
                text(
                    """
                    SELECT order_id, status, tracking_number, timestamp, notes
                    FROM order_status_logs
                    WHERE order_id = ANY(:ids)
                      AND timestamp >= '2026-06-16 20:00:00'
                    ORDER BY order_id, timestamp
                    """
                ),
                {"ids": INCIDENT_ORDER_IDS},
            ).fetchall()
            for lg in logs:
                print(f"  {lg.order_id[-8:]} {lg.timestamp} {lg.status:12} {lg.tracking_number or ''}")

            print("\n=== Duplicate wfirma numbers among incident orders ===")
            dupes = db.execute(
                text(
                    """
                    SELECT wfirma_invoice_number, count(*), array_agg(order_id)
                    FROM orders
                    WHERE order_id = ANY(:ids)
                      AND wfirma_invoice_number IS NOT NULL AND wfirma_invoice_number != ''
                    GROUP BY wfirma_invoice_number
                    HAVING count(*) > 1
                    """
                ),
                {"ids": INCIDENT_ORDER_IDS},
            ).fetchall()
            if not dupes:
                print("  none")
            for d in dupes:
                print(f"  {d.wfirma_invoice_number}: {d.count} orders -> {d.array_agg}")

            print("\n=== printed_orders last_order_data waybills ===")
            po_rows = db.execute(
                text(
                    """
                    SELECT order_id, printed_at, last_order_data
                    FROM printed_orders
                    WHERE order_id = ANY(:ids)
                    """
                ),
                {"ids": INCIDENT_ORDER_IDS},
            ).fetchall()
            for pr in po_rows:
                data = pr.last_order_data
                if isinstance(data, str):
                    data = json.loads(data)
                wb = (data or {}).get("delivery_package_nr", "-")
                pkgs = (data or {}).get("package_ids", [])
                print(f"  {pr.order_id[-8:]} printed={pr.printed_at} waybill={wb} packages={len(pkgs)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
