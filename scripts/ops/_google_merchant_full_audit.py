#!/usr/bin/env python3
"""Full Merchant API issue inventory with actionable fields."""
from __future__ import annotations

import json
import os
from collections import defaultdict

from _merchant_api import (
    access_token,
    issue_servability,
    list_products,
    merchant_id,
    normalized_price,
    product_input_name,
)


def main() -> int:
    mid = merchant_id()
    products = list_products(access_token(), mid)

    by_code: dict[str, list] = defaultdict(list)
    for product in products:
        attributes = product.get("productAttributes") or {}
        status = product.get("productStatus") or {}
        for iss in status.get("itemLevelIssues") or []:
            code = iss.get("code")
            by_code[code].append(
                {
                    "productId": product.get("name"),
                    "productInputName": product_input_name(product),
                    "dataSource": product.get("dataSource"),
                    "offerId": product.get("offerId"),
                    "title": attributes.get("title"),
                    "link": attributes.get("link"),
                    "imageLink": attributes.get("imageLink"),
                    "price": normalized_price(attributes.get("price")),
                    "availability": attributes.get("availability"),
                    "condition": attributes.get("condition"),
                    "brand": attributes.get("brand"),
                    "gtin": attributes.get("gtin"),
                    "mpn": attributes.get("mpn"),
                    "identifierExists": attributes.get("identifierExists"),
                    "servability": issue_servability(iss.get("severity")),
                    "severity": iss.get("severity"),
                    "description": iss.get("description"),
                    "detail": iss.get("detail"),
                    "attributeName": iss.get("attribute"),
                    "resolution": iss.get("resolution"),
                }
            )

    out = {
        "api": "Merchant API products/v1",
        "merchant_id": mid,
        "statuses": len(products),
        "products": len(products),
        "issue_counts": {k: len(v) for k, v in sorted(by_code.items(), key=lambda x: -len(x[1]))},
        "issues": {k: v for k, v in by_code.items()},
    }
    path = os.path.expanduser("~/retrievershop-suite/scripts/ops/_merchant_audit.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(json.dumps({"saved": path, "issue_counts": out["issue_counts"], "statuses": out["statuses"]}, indent=2))
    # compact unique lists per code
    for code, rows in sorted(by_code.items(), key=lambda x: -len(x[1])):
        uniq = {}
        for r in rows:
            uniq[r["productId"]] = r
        print(f"\n## {code} ({len(rows)} issues / {len(uniq)} products) serv={rows[0].get('servability')}")
        for r in list(uniq.values())[:30]:
            price = r.get("price")
            price_s = f"{price.get('value')} {price.get('currency')}" if isinstance(price, dict) else price
            print(
                f"- {r.get('offerId')}: {r.get('title')}\n"
                f"  link={r.get('link')} price={price_s} avail={r.get('availability')} "
                f"gtin={r.get('gtin')} mpn={r.get('mpn')} brand={r.get('brand')} "
                f"attr={r.get('attributeName')} :: {r.get('description')}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
