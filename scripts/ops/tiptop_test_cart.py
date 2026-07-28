#!/usr/bin/env python3
"""Test TipTop Front basket fill and verify contents match the order.

Run locally or: docker exec -i retrievershop-magazyn python - < scripts/ops/tiptop_test_cart.py
"""

from __future__ import annotations

import json
import sys

import requests

BASKET = "https://tiptop24.pl/webapi/front/pl_PL/basket/PLN/"
HOME = "https://tiptop24.pl/"

# Controlled test order — known working mappings from live TipTop pages.
ORDER = [
    {
        "label": "Obroża Active / L / czarny",
        "stock_id": 214,
        "quantity": 2,
        "options": {"8": 51, "9": 60},
    },
    {
        "label": "Obroża Active / M / czerwony",
        "stock_id": 214,
        "quantity": 1,
        "options": {"8": 50, "9": 161},
    },
]


def main() -> int:
    sess = requests.Session()
    sess.headers.update(
        {
            "User-Agent": "RetrieverShopMagazyn/1.0 TipTopCartTest",
            "Accept": "application/json",
            "Accept-Language": "pl-PL,pl;q=0.9",
        }
    )
    # Warm session / cookies
    r = sess.get(HOME, timeout=30)
    r.raise_for_status()

    # Clear basket if anything leftover — TipTop may not expose clear; remove via API if present
    before = sess.get(BASKET, timeout=30).json()
    print("BEFORE count=", before.get("basket", {}).get("count"), "products=", len(before.get("products") or []))

    added = []
    errors = []
    for item in ORDER:
        payload = {
            "stock_id": item["stock_id"],
            "quantity": item["quantity"],
            "options": item["options"],
        }
        resp = sess.post(
            BASKET,
            data=json.dumps(payload),
            headers={"Content-Type": "application/json;charset=UTF-8", "X-Requested-With": "XMLHttpRequest"},
            timeout=30,
        )
        data = resp.json()
        flash_err = (data.get("_flash_messenger") or {}).get("error") or []
        if flash_err or not data.get("added"):
            errors.append({"item": item["label"], "error": flash_err or data})
            print("FAIL add", item["label"], flash_err or data)
        else:
            for a in data["added"]:
                added.append(
                    {
                        "ordered_label": item["label"],
                        "ordered_qty": item["quantity"],
                        "name": a.get("name"),
                        "variant": a.get("variant"),
                        "quantity": a.get("quantity"),
                        "stock_id": a.get("stock_id"),
                    }
                )
                print(
                    "OK add",
                    item["label"],
                    "->",
                    a.get("name"),
                    a.get("variant"),
                    "qty=",
                    a.get("quantity"),
                )

    basket = sess.get(BASKET, timeout=30).json()
    products = basket.get("products") or []
    print("\nBASKET count=", basket.get("basket", {}).get("count"))
    print("BASKET sum=", basket.get("basket", {}).get("sum"))
    for p in products:
        print(
            " -",
            p.get("quantity"),
            "x",
            p.get("name"),
            "|",
            p.get("variant"),
            "| stock_id=",
            p.get("stock_id"),
        )

    # Verify: each ordered line appears with expected size/color tokens and quantity
    mismatches = []
    for item in ORDER:
        # expected tokens from label: "... / SIZE / COLOR"
        parts = [x.strip().lower() for x in item["label"].split("/")]
        size = parts[1] if len(parts) > 1 else ""
        color = parts[2] if len(parts) > 2 else ""
        matches = [
            p
            for p in products
            if size
            and size in (p.get("variant") or "").lower()
            and color
            and color in (p.get("variant") or "").lower()
            and "active" in (p.get("name") or "").lower()
        ]
        if not matches:
            mismatches.append(f"missing in basket: {item['label']}")
            continue
        qty = sum(int(p.get("quantity") or 0) for p in matches)
        if qty != item["quantity"]:
            mismatches.append(
                f"qty mismatch for {item['label']}: ordered={item['quantity']} basket={qty}"
            )

    total_ordered = sum(i["quantity"] for i in ORDER)
    basket_count = int(basket.get("basket", {}).get("count") or 0)
    if basket_count != total_ordered:
        mismatches.append(f"basket count {basket_count} != ordered total {total_ordered}")

    print("\nADDED rows:", json.dumps(added, ensure_ascii=False, indent=2))
    if errors:
        print("ERRORS:", json.dumps(errors, ensure_ascii=False, indent=2))
    if mismatches:
        print("MISMATCHES:")
        for m in mismatches:
            print(" -", m)
        return 1

    print("\nVERDICT: OK — koszyk TipTop zgodny z zamówieniem testowym")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
