#!/usr/bin/env python3
"""Audit wFirma invoices vs orders DB — find duplicates in last N months."""
from __future__ import annotations

import argparse
import re
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import text

from magazyn.db import get_session
from magazyn.factory import create_app
from magazyn.wfirma_api.client import WFirmaClient, WFirmaError

ORDER_DESC_RE = re.compile(r"^Zamowienie\s+(\S+)\s*$", re.IGNORECASE)
PAGE_SIZE = 100


def _parse_invoices_response(result: dict) -> tuple[list[dict], dict]:
    """Extract invoice dicts and pagination parameters from find response."""
    block = result.get("invoices", {})
    params = block.get("parameters", {}) if isinstance(block, dict) else {}
    invoices: list[dict] = []

    if isinstance(block, dict):
        for key in sorted(block):
            if key == "parameters":
                continue
            entry = block[key]
            if isinstance(entry, dict) and "invoice" in entry:
                invoices.append(entry["invoice"])
    elif isinstance(block, list):
        for entry in block:
            if isinstance(entry, dict) and "invoice" in entry:
                invoices.append(entry["invoice"])

    return invoices, params if isinstance(params, dict) else {}


def fetch_invoices(
    client: WFirmaClient,
    date_from: str,
    date_to: str,
    invoice_type: Optional[str] = "bill",
) -> list[dict]:
    """Paginate invoices/find for date range."""
    all_invoices: list[dict] = []
    page = 1

    while True:
        conditions: list[dict] = [
            {
                "condition": {
                    "field": "date",
                    "operator": "ge",
                    "value": date_from,
                }
            },
            {
                "condition": {
                    "field": "date",
                    "operator": "le",
                    "value": date_to,
                }
            },
        ]
        if invoice_type:
            conditions.append(
                {
                    "condition": {
                        "field": "type",
                        "operator": "eq",
                        "value": invoice_type,
                    }
                }
            )

        data = {
            "invoices": {
                "parameters": {
                    "conditions": {"and": conditions},
                    "fields": [
                        {"field": "Invoice.id"},
                        {"field": "Invoice.fullnumber"},
                        {"field": "Invoice.date"},
                        {"field": "Invoice.type"},
                        {"field": "Invoice.total"},
                        {"field": "Invoice.description"},
                        {"field": "Invoice.created"},
                        {"field": "ContractorDetail.name"},
                    ],
                    "order": [{"asc": "date"}, {"asc": "fullnumber"}],
                    "page": page,
                    "limit": PAGE_SIZE,
                }
            }
        }

        result = client.request("invoices/find", data=data)
        batch, params = _parse_invoices_response(result)
        all_invoices.extend(batch)

        total = int(params.get("total") or 0)
        if not batch or len(all_invoices) >= total:
            break
        page += 1

    return all_invoices


def _money(val: Any) -> Decimal:
    try:
        return Decimal(str(val or 0)).quantize(Decimal("0.01"))
    except Exception:
        return Decimal("0.00")


def _order_id_from_description(desc: Optional[str]) -> Optional[str]:
    if not desc:
        return None
    m = ORDER_DESC_RE.match(desc.strip())
    return m.group(1) if m else None


def load_db_orders(date_from_ts: int, date_to_ts: int) -> list:
    """Orders with invoice data in period (by order date_add)."""
    with get_session() as db:
        return db.execute(
            text(
                """
                SELECT order_id, external_order_id, customer_name, date_add,
                       wfirma_invoice_id, wfirma_invoice_number,
                       payment_done, delivery_price
                FROM orders
                WHERE date_add >= :from_ts AND date_add <= :to_ts
                ORDER BY date_add
                """
            ),
            {"from_ts": date_from_ts, "to_ts": date_to_ts},
        ).fetchall()


def load_all_invoiced_orders() -> list:
    with get_session() as db:
        return db.execute(
            text(
                """
                SELECT order_id, customer_name, date_add,
                       wfirma_invoice_id, wfirma_invoice_number, payment_done
                FROM orders
                WHERE wfirma_invoice_id IS NOT NULL
                ORDER BY wfirma_invoice_id
                """
            )
        ).fetchall()


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit wFirma invoices vs orders")
    parser.add_argument(
        "--months",
        type=int,
        default=3,
        help="Look back N months from today (default: 3)",
    )
    parser.add_argument(
        "--date-from",
        help="Override start date YYYY-MM-DD",
    )
    parser.add_argument(
        "--date-to",
        help="Override end date YYYY-MM-DD (default: today)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable duplicate list only",
    )
    args = parser.parse_args()

    today = date.today()
    date_to = args.date_to or today.isoformat()
    if args.date_from:
        date_from = args.date_from
    else:
        dt_to = date.fromisoformat(date_to)
        date_from = (dt_to - timedelta(days=30 * args.months)).isoformat()

    from_ts = int(date.fromisoformat(date_from).strftime("%s"))
    to_ts = int(date.fromisoformat(date_to).strftime("%s")) + 86399

    app = create_app()
    with app.app_context():
        print(f"=== Audyt faktur wFirma {date_from} .. {date_to} ===\n")

        try:
            client = WFirmaClient.from_settings()
        except WFirmaError as exc:
            print(f"Błąd klienta wFirma: {exc}")
            return 1

        print("Pobieram rachunki (type=bill) z wFirma...")
        wf_invoices = fetch_invoices(client, date_from, date_to, invoice_type="bill")
        print(f"  Pobrano {len(wf_invoices)} rachunków z wFirma\n")

        db_orders = load_db_orders(from_ts, to_ts)
        db_invoiced = load_all_invoiced_orders()
        print(f"  Zamówienia w okresie (DB): {len(db_orders)}")
        print(f"  Zamówienia z fakturą (DB, wszystkie): {len(db_invoiced)}\n")

        # Index DB
        by_invoice_id: dict[int, list] = defaultdict(list)
        by_invoice_number: dict[str, list] = defaultdict(list)
        by_order_id: dict[str, dict] = {}

        for row in db_invoiced:
            if row.wfirma_invoice_id:
                by_invoice_id[int(row.wfirma_invoice_id)].append(row)
            if row.wfirma_invoice_number:
                by_invoice_number[row.wfirma_invoice_number.strip()].append(row)
            by_order_id[row.order_id] = row

        # Index wFirma by order_id from description
        wf_by_order: dict[str, list[dict]] = defaultdict(list)
        wf_by_id: dict[int, dict] = {}
        wf_no_order: list[dict] = []

        for inv in wf_invoices:
            inv_id = int(inv.get("id") or 0)
            wf_by_id[inv_id] = inv
            oid = _order_id_from_description(inv.get("description"))
            if oid:
                wf_by_order[oid].append(inv)
            else:
                wf_no_order.append(inv)

        duplicates: list[dict] = []

        def add_dupe(category: str, **fields: Any) -> None:
            entry = {"category": category, **fields}
            duplicates.append(entry)

        # A) Ten sam wfirma_invoice_id przypisany do wielu orderów w DB
        print("--- A) Duplikat wfirma_invoice_id w DB ---")
        found_a = False
        for inv_id, rows in sorted(by_invoice_id.items()):
            if len(rows) > 1:
                found_a = True
                nums = ", ".join(r.order_id[-12:] for r in rows)
                print(f"  id={inv_id} -> {len(rows)} orderów: {nums}")
                add_dupe(
                    "db_invoice_id_shared",
                    wfirma_invoice_id=inv_id,
                    order_ids=[r.order_id for r in rows],
                )
        if not found_a:
            print("  brak")

        # B) Ten sam numer faktury w DB na wielu orderach
        print("\n--- B) Duplikat wfirma_invoice_number w DB ---")
        found_b = False
        for num, rows in sorted(by_invoice_number.items()):
            if len(rows) > 1:
                found_b = True
                print(f"  {num} -> {len(rows)} orderów")
                add_dupe(
                    "db_invoice_number_shared",
                    invoice_number=num,
                    order_ids=[r.order_id for r in rows],
                )
        if not found_b:
            print("  brak")

        # C) Wiele faktur w wFirma dla tego samego order_id (opis)
        print("\n--- C) Wiele rachunków wFirma dla jednego zamówienia ---")
        excess_total = Decimal("0.00")
        found_c = False
        for oid, invs in sorted(wf_by_order.items()):
            if len(invs) <= 1:
                continue
            found_c = True
            invs_sorted = sorted(invs, key=lambda x: int(x.get("id") or 0))
            db_row = by_order_id.get(oid)
            db_id = int(db_row.wfirma_invoice_id) if db_row and db_row.wfirma_invoice_id else None

            # Faktura „prawidłowa” = ta w DB; reszta to duplikaty
            legit_id = db_id
            if legit_id is None:
                legit_id = int(invs_sorted[0].get("id") or 0)

            dup_invs = [i for i in invs_sorted if int(i.get("id") or 0) != legit_id]
            dup_sum = sum(_money(i.get("total")) for i in dup_invs)
            excess_total += dup_sum

            nums = ", ".join(
                f"{i.get('fullnumber')} (id={i.get('id')}, {_money(i.get('total'))} PLN)"
                for i in invs_sorted
            )
            db_info = (
                f"DB: {db_row.wfirma_invoice_number} id={db_id}"
                if db_row
                else "BRAK w DB"
            )
            print(f"  {oid[-20:]}: {len(invs)} faktur | {db_info}")
            print(f"    {nums}")
            print(f"    nadwyżka (duplikaty): {dup_sum} PLN")

            add_dupe(
                "wfirma_multiple_per_order",
                order_id=oid,
                customer=db_row.customer_name if db_row else invs[0].get("contractor_detail", {}).get("name"),
                invoices=[
                    {
                        "id": int(i.get("id") or 0),
                        "number": i.get("fullnumber"),
                        "date": i.get("date"),
                        "total": float(_money(i.get("total"))),
                        "is_in_db": int(i.get("id") or 0) == db_id,
                    }
                    for i in invs_sorted
                ],
                excess_pln=float(dup_sum),
                duplicate_invoice_ids=[int(i.get("id") or 0) for i in dup_invs],
            )
        if not found_c:
            print("  brak")
        else:
            print(f"\n  SUMA nadwyżki (C): {excess_total} PLN")

        # D) Faktury w wFirma bez powiązania w DB (id nie w DB)
        print("\n--- D) Rachunki wFirma bez wpisu w orders.wfirma_invoice_id ---")
        db_invoice_ids = {int(r.wfirma_invoice_id) for r in db_invoiced if r.wfirma_invoice_id}
        orphan_total = Decimal("0.00")
        found_d = False
        for inv in sorted(wf_invoices, key=lambda x: int(x.get("id") or 0)):
            inv_id = int(inv.get("id") or 0)
            if inv_id in db_invoice_ids:
                continue
            found_d = True
            amt = _money(inv.get("total"))
            orphan_total += amt
            oid = _order_id_from_description(inv.get("description")) or "?"
            print(
                f"  {inv.get('fullnumber')} id={inv_id} {amt} PLN "
                f"date={inv.get('date')} order={oid[-20:]}"
            )
            add_dupe(
                "wfirma_orphan_not_in_db",
                wfirma_invoice_id=inv_id,
                invoice_number=inv.get("fullnumber"),
                date=inv.get("date"),
                total=float(amt),
                order_id=oid if oid != "?" else None,
                description=inv.get("description"),
            )
        if not found_d:
            print("  brak")
        else:
            print(f"\n  SUMA osieroconych (D): {orphan_total} PLN")

        # E) Order ma fakturę w DB, ale w wFirma jest inna dodatkowa
        print("\n--- E) Zamówienia z fakturą w DB + dodatkowa faktura w wFirma ---")
        found_e = False
        for oid, invs in sorted(wf_by_order.items()):
            if len(invs) <= 1:
                continue
            db_row = by_order_id.get(oid)
            if not db_row or not db_row.wfirma_invoice_id:
                continue
            db_id = int(db_row.wfirma_invoice_id)
            extra = [i for i in invs if int(i.get("id") or 0) != db_id]
            if not extra:
                continue
            found_e = True
            for ex in extra:
                print(
                    f"  {oid[-20:]} DB={db_row.wfirma_invoice_number} "
                    f"EXTRA={ex.get('fullnumber')} id={ex.get('id')} "
                    f"{_money(ex.get('total'))} PLN"
                )
        if not found_e:
            print("  (pokryte w sekcji C)")

        # F) Faktury wFirma z opisem zamówienia, ale order bez faktury w DB
        print("\n--- F) wFirma ma fakturę, order w DB bez wfirma_invoice_id ---")
        found_f = False
        for oid, invs in sorted(wf_by_order.items()):
            db_row = by_order_id.get(oid)
            if db_row and db_row.wfirma_invoice_id:
                continue
            found_f = True
            for inv in invs:
                print(
                    f"  {oid[-20:]} -> {inv.get('fullnumber')} "
                    f"id={inv.get('id')} {_money(inv.get('total'))} PLN "
                    f"(order {'istnieje' if db_row else 'BRAK w invoiced'})"
                )
                add_dupe(
                    "wfirma_invoice_order_not_linked",
                    order_id=oid,
                    wfirma_invoice_id=int(inv.get("id") or 0),
                    invoice_number=inv.get("fullnumber"),
                    total=float(_money(inv.get("total"))),
                )
        if not found_f:
            print("  brak")

        # G) Rachunki bez opisu zamówienia
        if wf_no_order:
            print(f"\n--- G) Rachunki bez opisu 'Zamowienie ...' ({len(wf_no_order)}) ---")
            for inv in wf_no_order[:20]:
                print(
                    f"  {inv.get('fullnumber')} id={inv.get('id')} "
                    f"desc={inv.get('description')!r}"
                )
            if len(wf_no_order) > 20:
                print(f"  ... i {len(wf_no_order) - 20} więcej")

        # Podsumowanie
        print("\n=== PODSUMOWANIE ===")
        print(f"Okres: {date_from} .. {date_to}")
        print(f"Rachunki wFirma: {len(wf_invoices)}")
        dup_categories = defaultdict(int)
        for d in duplicates:
            dup_categories[d["category"]] += 1
        for cat, cnt in sorted(dup_categories.items()):
            print(f"  {cat}: {cnt}")
        print(f"Szacowana nadwyżka księgowa (duplikaty C): {excess_total} PLN")
        print(f"Osierocone faktury wFirma (D): {orphan_total} PLN")

        if args.json:
            import json

            print(json.dumps(duplicates, ensure_ascii=False, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
