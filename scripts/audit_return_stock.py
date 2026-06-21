#!/usr/bin/env python3
"""Audyt poprawnosci przywracania stanu magazynowego dla ostatnich zwrotow."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from magazyn.factory import create_app
from magazyn.models.allegro import AllegroOffer
from magazyn.models.orders import OrderProduct
from magazyn.models.products import ProductSize
from magazyn.models.returns import Return, ReturnStatusLog


def _match_by_product_size_id(db, item: dict) -> ProductSize | None:
    product_size_id = item.get("product_size_id")
    if not product_size_id:
        return None
    return db.query(ProductSize).filter(ProductSize.id == product_size_id).first()


def _match_by_ean(db, ean: str | None) -> ProductSize | None:
    if not ean:
        return None
    return db.query(ProductSize).filter(ProductSize.barcode == ean).first()


def _match_by_order_ean_auction(db, order_id: str, ean: str | None) -> tuple[ProductSize | None, str]:
    """Obecna logika z return_stock.py (bez offerId)."""
    order_products = db.query(OrderProduct).filter(OrderProduct.order_id == order_id).all()
    null_ean_count = sum(1 for op in order_products if not op.ean)

    order_product = db.query(OrderProduct).filter(
        OrderProduct.order_id == order_id,
        OrderProduct.ean == ean,
    ).first()

    if not order_product:
        if ean is None and null_ean_count > 1:
            return None, f"ambiguous_null_ean({null_ean_count}_products)"
        return None, "no_order_product"

    if not order_product.auction_id:
        return None, "missing_auction_id"

    allegro_offer = db.query(AllegroOffer).filter(
        AllegroOffer.offer_id == order_product.auction_id,
    ).first()
    if not allegro_offer or not allegro_offer.product_size_id:
        return None, "no_allegro_offer_mapping"

    product_size = db.query(ProductSize).filter(
        ProductSize.id == allegro_offer.product_size_id,
    ).first()
    if not product_size:
        return None, "product_size_missing"
    return product_size, "order_ean_auction"


def _match_by_offer_id(db, offer_id: str | None) -> tuple[ProductSize | None, str]:
    if not offer_id:
        return None, "no_offer_id"
    offer_id = str(offer_id)
    allegro_offer = db.query(AllegroOffer).filter(AllegroOffer.offer_id == offer_id).first()
    if not allegro_offer or not allegro_offer.product_size_id:
        return None, "offer_not_mapped"
    product_size = db.query(ProductSize).filter(ProductSize.id == allegro_offer.product_size_id).first()
    if not product_size:
        return None, "product_size_missing"
    return product_size, "offer_id"


def _current_match(db, return_record: Return, item: dict) -> tuple[ProductSize | None, str]:
    product_size = _match_by_product_size_id(db, item)
    if product_size:
        return product_size, "product_size_id"

    ean = item.get("ean")
    product_size = _match_by_ean(db, ean)
    if product_size:
        return product_size, "ean"

    return _match_by_order_ean_auction(db, return_record.order_id, ean)


def _expected_match(db, return_record: Return, item: dict) -> tuple[ProductSize | None, str]:
    product_size = _match_by_product_size_id(db, item)
    if product_size:
        return product_size, "product_size_id"

    ean = item.get("ean")
    product_size = _match_by_ean(db, ean)
    if product_size:
        return product_size, "ean"

    offer_id = item.get("offerId")
    product_size, method = _match_by_offer_id(db, offer_id)
    if product_size:
        return product_size, method

    return _match_by_order_ean_auction(db, return_record.order_id, ean)


def _restore_log_note(db, return_id: int) -> str | None:
    row = (
        db.query(ReturnStatusLog)
        .filter(
            ReturnStatusLog.return_id == return_id,
            ReturnStatusLog.notes.like("Przywrocono stan:%"),
        )
        .order_by(ReturnStatusLog.id.desc())
        .first()
    )
    return row.notes if row else None


def _parse_restore_log(note: str) -> list[dict]:
    """Wyciaga '+qty (bylo: old)' z logu przywracania."""
    entries = []
    for part in note.replace("Przywrocono stan: ", "").split(", "):
        match = re.search(r" \+(\d+) \(bylo: (\d+)\)$", part)
        if match:
            entries.append(
                {
                    "label": part[: match.start()].strip(),
                    "qty": int(match.group(1)),
                    "old_qty": int(match.group(2)),
                }
            )
    return entries


def audit_returns(limit: int = 50) -> dict:
    app = create_app()
    with app.app_context():
        from magazyn.db import get_session

        with get_session() as db:
            returns = (
                db.query(Return)
                .order_by(Return.id.desc())
                .limit(limit)
                .all()
            )

            summary = {
                "total": len(returns),
                "stock_restored": 0,
                "not_restored_delivered": 0,
                "ok": 0,
                "risky_match": 0,
                "would_fail_now": 0,
                "current_vs_expected_mismatch": 0,
                "items": [],
            }

            for ret in returns:
                items = json.loads(ret.items_json) if ret.items_json else []
                restore_note = _restore_log_note(db, ret.id)
                restore_entries = _parse_restore_log(restore_note) if restore_note else []

                order_products = db.query(OrderProduct).filter(
                    OrderProduct.order_id == ret.order_id
                ).all()
                null_ean_in_order = sum(1 for op in order_products if not op.ean)

                item_results = []
                issues = []

                for idx, item in enumerate(items):
                    current_ps, current_method = _current_match(db, ret, item)
                    expected_ps, expected_method = _expected_match(db, ret, item)

                    item_issue = []
                    if current_ps is None and expected_ps is not None:
                        item_issue.append("current_logic_would_fail")
                        summary["would_fail_now"] += 1
                    elif (
                        current_ps
                        and expected_ps
                        and current_ps.id != expected_ps.id
                    ):
                        item_issue.append("current_vs_expected_mismatch")
                        summary["current_vs_expected_mismatch"] += 1

                    if current_method == "ambiguous_null_ean" or (
                        not item.get("ean")
                        and not item.get("offerId")
                        and null_ean_in_order > 1
                        and current_ps is not None
                        and current_method == "order_ean_auction"
                    ):
                        item_issue.append("risky_null_ean_first_match")
                        summary["risky_match"] += 1

                    item_results.append(
                        {
                            "name": item.get("name"),
                            "quantity": item.get("quantity", 1),
                            "ean": item.get("ean"),
                            "offerId": item.get("offerId"),
                            "current_match": {
                                "product_size_id": current_ps.id if current_ps else None,
                                "barcode": current_ps.barcode if current_ps else None,
                                "size": current_ps.size if current_ps else None,
                                "method": current_method,
                            },
                            "expected_match": {
                                "product_size_id": expected_ps.id if expected_ps else None,
                                "barcode": expected_ps.barcode if expected_ps else None,
                                "size": expected_ps.size if expected_ps else None,
                                "method": expected_method,
                            },
                            "issues": item_issue,
                        }
                    )
                    issues.extend(item_issue)

                if ret.stock_restored:
                    summary["stock_restored"] += 1
                elif ret.status in ("delivered", "not_collected", "completed"):
                    summary["not_restored_delivered"] += 1
                    issues.append("not_restored_but_delivered")

                if ret.stock_restored and restore_note and not issues:
                    summary["ok"] += 1
                elif ret.stock_restored and restore_note and issues:
                    pass
                elif ret.stock_restored and not restore_note:
                    issues.append("stock_restored_without_log")

                if ret.stock_restored and len(restore_entries) != len(items):
                    issues.append(
                        f"log_items_mismatch(log={len(restore_entries)}, items={len(items)})"
                    )

                summary["items"].append(
                    {
                        "return_id": ret.id,
                        "order_id": ret.order_id,
                        "status": ret.status,
                        "stock_restored": bool(ret.stock_restored),
                        "order_product_count": len(order_products),
                        "null_ean_in_order": null_ean_in_order,
                        "return_item_count": len(items),
                        "restore_note": restore_note,
                        "restore_entries": restore_entries,
                        "items": item_results,
                        "issues": sorted(set(issues)),
                    }
                )

            return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Audyt przywracania stanu magazynowego zwrotow")
    parser.add_argument("--limit", type=int, default=50, help="Liczba ostatnich zwrotow")
    parser.add_argument("--json", action="store_true", help="Pelny JSON")
    parser.add_argument("--issues-only", action="store_true", help="Tylko zwroty z problemami")
    parser.add_argument("--summary-json", action="store_true", help="Podsumowanie kategorii JSON")
    args = parser.parse_args()

    if args.summary_json:
        print_summary(limit=args.limit)
        return

    summary = audit_returns(limit=args.limit)
    rows = summary["items"]
    if args.issues_only:
        rows = [row for row in rows if row["issues"] or any(i["issues"] for i in row["items"])]

    if args.json:
        payload = {**summary, "items": rows}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    print(f"Audyt ostatnich {summary['total']} zwrotow")
    print(
        f"  stock_restored={summary['stock_restored']}, "
        f"ok={summary['ok']}, "
        f"not_restored_delivered={summary['not_restored_delivered']}, "
        f"risky_match={summary['risky_match']}, "
        f"current_vs_expected_mismatch={summary['current_vs_expected_mismatch']}, "
        f"would_fail_now={summary['would_fail_now']}"
    )
    print()

    for row in rows:
        has_issue = row["issues"] or any(i["issues"] for i in row["items"])
        if args.issues_only and not has_issue:
            continue

        flag = "OK" if not has_issue else "ISSUE"
        print(
            f"[{flag}] #{row['return_id']} {row['order_id']} "
            f"status={row['status']} stock_restored={row['stock_restored']} "
            f"items={row['return_item_count']} null_ean_order={row['null_ean_in_order']}"
        )
        if row["issues"]:
            print(f"  issues: {', '.join(row['issues'])}")
        if row["restore_note"]:
            print(f"  log: {row['restore_note']}")
        for item in row["items"]:
            cur = item["current_match"]
            exp = item["expected_match"]
            print(
                f"  - {item['name'][:60]} qty={item['quantity']} "
                f"offerId={item.get('offerId')} ean={item.get('ean')}"
            )
            print(
                f"    current: {cur['size']} ({cur['barcode']}) via {cur['method']}"
            )
            if cur != exp:
                print(
                    f"    expected: {exp['size']} ({exp['barcode']}) via {exp['method']}"
                )
            if item["issues"]:
                print(f"    item_issues: {', '.join(item['issues'])}")
        print()


def print_summary(limit: int = 50) -> None:
    summary = audit_returns(limit=limit)
    categories: dict[str, list] = {
        "ok": [],
        "wrong_product": [],
        "not_restored": [],
        "restored_then_items_overwritten": [],
        "other": [],
    }
    for row in summary["items"]:
        issues = set(row["issues"])
        if row["stock_restored"] and "current_vs_expected_mismatch" in issues:
            categories["wrong_product"].append(row["return_id"])
        elif row["stock_restored"] and not issues and not any(i["issues"] for i in row["items"]):
            categories["ok"].append(row["return_id"])
        elif not row["stock_restored"] and "not_restored_but_delivered" in issues:
            categories["not_restored"].append(row["return_id"])
        elif row["stock_restored"] and "current_logic_would_fail" in issues:
            categories["restored_then_items_overwritten"].append(row["return_id"])
        else:
            categories["other"].append({"return_id": row["return_id"], "issues": sorted(issues)})

    print(json.dumps({"summary": {k: v for k, v in summary.items() if k != "items"}, "categories": categories}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
