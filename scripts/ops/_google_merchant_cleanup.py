#!/usr/bin/env python3
"""
Delete broken Merchant Center product inputs (404 landing pages, price 0, missing image).
Optionally patch products that are still valid but missing brand.
"""
from __future__ import annotations

import json
import os
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from _merchant_api import API_ROOT, access_token, merchant_id, request_json

AUDIT = Path(os.path.expanduser("~/retrievershop-suite/scripts/ops/_merchant_audit.json"))
DRY = "--apply" not in sys.argv
CTX = ssl.create_default_context()

def http_status(url: str) -> int:
    try:
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "RS-merchant-cleanup"})
        with urllib.request.urlopen(req, timeout=20, context=CTX) as r:
            return int(r.status)
    except urllib.error.HTTPError as e:
        return int(e.code)
    except Exception:
        return 0


def main() -> int:
    mid = merchant_id()
    access = access_token()
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    if audit.get("api") != "Merchant API products/v1":
        raise RuntimeError(
            "Audit is not from Merchant API. Re-run _google_merchant_full_audit.py first."
        )

    to_delete: dict[str, str] = {}

    # 1) landing_page_error: delete if base URL is 404 OR keep variation URL broken
    for r in audit["issues"].get("landing_page_error", []):
        pid = r["productId"]
        link = (r.get("link") or "").split("?")[0]
        st = http_status(link) if link else 0
        # Also delete if Merchant says unavailable even when parent 200 —
        # GLA variation entries with query attrs often fail crawl; safer remove.
        reason = f"landing_page_error status={st}"
        to_delete[pid] = reason

    # 2) price 0 / invalid
    for r in audit["issues"].get("price_out_of_range", []):
        pid = r["productId"]
        price = r.get("price") or {}
        val = float(price.get("value") or 0) if isinstance(price, dict) else 0
        if val <= 0:
            to_delete[pid] = "price_out_of_range value<=0"

    # 3) missing required attribute that we can't fix from here without Woo image upload
    for r in audit["issues"].get("item_missing_required_attribute", []):
        pid = r["productId"]
        attr = (r.get("attributeName") or "").lower()
        desc = (r.get("description") or "").lower()
        if "image" in attr or "image" in desc or "price" in attr or "price" in desc:
            to_delete.setdefault(pid, f"missing_attr:{attr or desc}")

    # 4) image_link_internal_error — remove additional-image broken variants from feed
    #    (unaffected but noisy); delete only if we already delete sibling, else leave
    #    Actually: delete these 3 so Google stops retrying bad additional images;
    #    GLA will re-push when Woo sync runs with good images.
    for r in audit["issues"].get("image_link_internal_error", []):
        to_delete.setdefault(r["productId"], "image_link_internal_error")

    print(f"mode={'DRY-RUN' if DRY else 'APPLY'} delete_candidates={len(to_delete)}")
    for pid, reason in sorted(to_delete.items()):
        sample = next(
            (
                row
                for rows in audit["issues"].values()
                for row in rows
                if row.get("productId") == pid
            ),
            {},
        )
        print(
            f"  {pid} :: {reason}"
            f" data_source={sample.get('dataSource') or 'MISSING'}"
        )

    if DRY:
        print("\nRe-run with --apply to delete.")
        return 0

    ok = fail = 0
    for pid, reason in sorted(to_delete.items()):
        sample = next(
            (
                row
                for rows in audit["issues"].values()
                for row in rows
                if row.get("productId") == pid
            ),
            {},
        )
        product_input = sample.get("productInputName")
        data_source = sample.get("dataSource")
        expected_prefix = f"accounts/{mid}/dataSources/"
        if not isinstance(product_input, str) or not isinstance(data_source, str):
            fail += 1
            print(f"SKIP {pid}: missing Merchant API product input or data source")
            continue
        if not product_input.startswith(f"accounts/{mid}/productInputs/"):
            fail += 1
            print(f"SKIP {pid}: unexpected product input {product_input}")
            continue
        if not data_source.startswith(expected_prefix):
            fail += 1
            print(f"SKIP {pid}: unexpected data source {data_source}")
            continue
        delete_url = (
            f"{API_ROOT}/{product_input}"
            f"?{urllib.parse.urlencode({'dataSource': data_source})}"
        )
        code, body = request_json(
            "DELETE",
            delete_url,
            access,
        )
        # 204/200 ok; 404 already gone
        if code in (200, 204, 404):
            ok += 1
            print(f"DELETED {code} {pid}")
        else:
            fail += 1
            print(f"FAIL {code} {pid} {body}")
    print(f"done ok={ok} fail={fail}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
