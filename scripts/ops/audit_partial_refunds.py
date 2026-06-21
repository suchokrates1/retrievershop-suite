#!/usr/bin/env python3
"""Audyt zwrotow czesciowych — porownanie kwoty oczekiwanej vs faktycznej."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from magazyn.factory import create_app
from magazyn import allegro_api
from magazyn.settings_store import settings_store
from magazyn.db import get_session
from magazyn.models.orders import Order, OrderProduct
from magazyn.models.returns import Return, ReturnStatusLog
from magazyn.allegro_api.refunds import build_partial_refund_details, build_checkout_refund_details


REFUND_LOG_RE = re.compile(
    r"Zwrot pieniedzy zainicjowany: return_id=([^,]+), kwota=([\d.]+) PLN"
)


def _load_refund_logs_from_agent() -> dict[str, float]:
    """return_id/order fragment -> kwota z agent.log (best effort)."""
    amounts: dict[str, float] = {}
    log_path = "/app/agent.log"
    if not os.path.exists(log_path):
        return amounts
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                match = REFUND_LOG_RE.search(line)
                if not match:
                    continue
                rid, amount = match.group(1), float(match.group(2))
                amounts[rid] = amount
    except OSError:
        pass
    return amounts


def _order_refund_amounts_from_logs() -> dict[str, float]:
    """order_id -> ostatnia kwota refundu z logow 'dla zamowienia'."""
    by_order: dict[str, float] = {}
    log_path = "/app/agent.log"
    if not os.path.exists(log_path):
        return by_order
    pair_re = re.compile(
        r"kwota=([\d.]+) PLN, refund_id=[^\n]+?\n"
        r".*?Zwrot pieniedzy dla zamowienia (\S+) przetworzony",
        re.DOTALL,
    )
    line_re = re.compile(
        r"Zwrot pieniedzy zainicjowany: return_id=([^,]+), kwota=([\d.]+) PLN"
    )
    order_re = re.compile(r"Zwrot pieniedzy dla zamowienia (\S+) przetworzony")

    pending: dict[str, float] = {}
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                m = line_re.search(line)
                if m:
                    pending[m.group(1)] = float(m.group(2))
                    continue
                m2 = order_re.search(line)
                if m2 and pending:
                    order_id = m2.group(1)
                    # ostatni pending — przybliżenie; lepiej mapować po kolejności
                    last_rid, last_amt = next(reversed(pending.items()))
                    by_order[order_id] = last_amt
                    pending.pop(last_rid, None)
    except OSError:
        pass
    return by_order


def _return_signature(return_items: list, order_products: list) -> dict:
    return_qty = sum(int(i.get("quantity", 1) or 1) for i in return_items)
    order_qty = sum(int(p.quantity or 1) for p in order_products)
    return_offers = {
        str(i.get("offerId") or i.get("offer_id") or i.get("auction_id") or "")
        for i in return_items
    } - {""}
    order_offers = {str(p.auction_id or "") for p in order_products} - {""}

    by_count = len(return_items) < len(order_products)
    by_qty = return_qty < order_qty
    by_offers = bool(order_offers and return_offers and return_offers < order_offers)

    return {
        "return_item_lines": len(return_items),
        "order_product_lines": len(order_products),
        "return_qty": return_qty,
        "order_qty": order_qty,
        "is_partial": by_count or by_qty or by_offers,
        "partial_reason": [
            x
            for x, flag in [
                ("fewer_lines", by_count),
                ("lower_qty", by_qty),
                ("subset_offers", by_offers),
            ]
            if flag
        ],
    }


def audit_partial_returns(limit: int = 200) -> dict:
    app = create_app()
    with app.app_context():
        token = settings_store.settings.ALLEGRO_ACCESS_TOKEN
        log_by_return_id = _load_refund_logs_from_agent()
        log_by_order = _order_refund_amounts_from_logs()

        with get_session() as db:
            returns = (
                db.query(Return)
                .filter(Return.allegro_return_id.isnot(None))
                .order_by(Return.id.desc())
                .limit(limit)
                .all()
            )

            partial_rows = []
            full_rows = []

            for ret in returns:
                items = json.loads(ret.items_json or "[]")
                if not items:
                    continue

                order = db.query(Order).filter(Order.order_id == ret.order_id).first()
                if not order or not order.external_order_id:
                    continue

                products = (
                    db.query(OrderProduct)
                    .filter(OrderProduct.order_id == ret.order_id)
                    .all()
                )
                sig = _return_signature(items, products)
                if not sig["is_partial"]:
                    continue

                checkout, checkout_err = allegro_api.get_checkout_form(
                    token, order.external_order_id
                )
                allegro_return, _ = allegro_api.get_customer_return(
                    token, ret.allegro_return_id
                )

                expected_partial, exp_err = (
                    build_partial_refund_details(items, checkout, delivery_cost_covered=True)
                    if checkout and not checkout_err
                    else (None, checkout_err)
                )
                expected_full = (
                    build_checkout_refund_details(checkout)
                    if checkout and not checkout_err
                    else None
                )

                actual = log_by_order.get(ret.order_id)
                if ret.allegro_return_id and ret.allegro_return_id in log_by_return_id:
                    actual = log_by_return_id[ret.allegro_return_id]

                payment_done = float(order.payment_done or 0)
                exp_partial_amt = (
                    float(expected_partial["total_amount"])
                    if expected_partial
                    else None
                )
                exp_full_amt = (
                    float(expected_full["total_amount"])
                    if expected_full
                    else payment_done
                )

                mismatch = None
                if actual is not None and exp_partial_amt is not None:
                    if abs(actual - exp_partial_amt) > 0.01:
                        if abs(actual - exp_full_amt) <= 0.01:
                            mismatch = "refunded_full_instead_of_partial"
                        else:
                            mismatch = "refunded_unexpected_amount"
                    else:
                        mismatch = "ok_partial"

                row = {
                    "return_id": ret.id,
                    "order_id": ret.order_id,
                    "status": ret.status,
                    "refund_processed": bool(ret.refund_processed),
                    "stock_restored": bool(ret.stock_restored),
                    "partial_reason": sig["partial_reason"],
                    "return_items": [
                        {
                            "name": i.get("name"),
                            "qty": i.get("quantity", 1),
                            "offerId": i.get("offerId"),
                            "price": (i.get("price") or {}).get("amount"),
                        }
                        for i in items
                    ],
                    "order_products": [
                        {
                            "name": p.name,
                            "qty": p.quantity,
                            "auction_id": p.auction_id,
                            "price": float(p.price_brutto or 0),
                        }
                        for p in products
                    ],
                    "payment_done": payment_done,
                    "expected_partial": exp_partial_amt,
                    "expected_full": exp_full_amt,
                    "actual_refund_log": actual,
                    "refund_check": mismatch,
                    "build_error": exp_err,
                    "allegro_status": (allegro_return or {}).get("status"),
                }
                partial_rows.append(row)

            return {
                "scanned": len(returns),
                "partial_count": len(partial_rows),
                "partial_returns": partial_rows,
            }


def scan_all_partial() -> list:
    app = create_app()
    with app.app_context():
        with get_session() as db:
            rows = []
            for ret in db.query(Return).order_by(Return.id.desc()).all():
                items = json.loads(ret.items_json or "[]")
                if not items:
                    continue
                prods = db.query(OrderProduct).filter(OrderProduct.order_id == ret.order_id).all()
                if not prods:
                    continue
                sig = _return_signature(items, prods)
                if sig["is_partial"]:
                    rows.append(
                        {
                            "return_id": ret.id,
                            "order_id": ret.order_id,
                            "refund_processed": bool(ret.refund_processed),
                            "stock_restored": bool(ret.stock_restored),
                            "status": ret.status,
                            **sig,
                            "has_allegro_return_id": bool(ret.allegro_return_id),
                        }
                    )
            return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--all-partial", action="store_true", help="Lista wszystkich czesciowych bez API")
    args = parser.parse_args()

    if args.all_partial:
        rows = scan_all_partial()
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return

    result = audit_partial_returns(limit=args.limit)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    print(f"Przeskanowano {result['scanned']} zwrotow Allegro, znaleziono {result['partial_count']} czesciowych\n")
    for row in result["partial_returns"]:
        flag = row["refund_check"] or "unknown"
        print(
            f"[{flag}] #{row['return_id']} {row['order_id']} "
            f"refund_processed={row['refund_processed']} "
            f"reason={','.join(row['partial_reason'])}"
        )
        print(
            f"  oczekiwany czesciowy={row['expected_partial']} zl, "
            f"pelny={row['expected_full']} zl, "
            f"log refund={row['actual_refund_log']} zl"
        )
        for i in row["return_items"]:
            print(f"  zwrot: {i['name'][:55]} qty={i['qty']} {i['price']} zl offer={i['offerId']}")
        for p in row["order_products"]:
            if not any(
                str(p["auction_id"]) == str(i.get("offerId"))
                for i in row["return_items"]
            ):
                print(f"  NIE zwrocono: {p['name'][:55]} qty={p['qty']} {p['price']} zl")
        print()


if __name__ == "__main__":
    main()
