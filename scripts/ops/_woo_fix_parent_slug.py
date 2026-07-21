#!/usr/bin/env python3
import os
import json
import sys

os.environ.setdefault("DISABLE_SCHEDULERS", "1")

from magazyn.factory import create_app
from magazyn.woocommerce_api import WooClient

PRODUCT_ID = int(sys.argv[1]) if len(sys.argv) > 1 else 3586
NEW_SLUG = sys.argv[2] if len(sys.argv) > 2 else "szelki-dla-psa-truelove-front-line-premium"
NEW_NAME = sys.argv[3] if len(sys.argv) > 3 else "Szelki dla psa Truelove Front Line Premium"

app = create_app()
with app.app_context():
    c = WooClient()
    p = c.get(f"wp-json/wc/v3/products/{PRODUCT_ID}")
    print("before_name=", p.get("name"))
    print("before_slug=", p.get("slug"))
    print("status=", p.get("status"))
    for a in p.get("attributes") or []:
        print("attr", a.get("name"), "var=", a.get("variation"), "opts=", len(a.get("options") or []))
    vars_ = c.get(f"wp-json/wc/v3/products/{PRODUCT_ID}/variations", params={"per_page": 100}) or []
    print("variations", len(vars_))
    colors = sorted(
        {
            next((x.get("option") for x in (v.get("attributes") or []) if x.get("name") == "Kolor"), "")
            for v in vars_
        }
    )
    print("var_colors", colors)
    updated = c.put(
        f"wp-json/wc/v3/products/{PRODUCT_ID}",
        json={"name": NEW_NAME, "slug": NEW_SLUG},
    )
    print("after_slug=", updated.get("slug"))
    print("after_name=", updated.get("name"))
    # rewrite redirects file to point to new slug
    redirects_path = "/tmp/rs_flp_redirects.json"
    try:
        with open(redirects_path, encoding="utf-8") as fh:
            redirects = json.load(fh)
    except FileNotFoundError:
        redirects = {}
    target = f"/produkt/{updated.get('slug')}/"
    # also redirect old canonical slug
    old_slug = p.get("slug") or ""
    if old_slug and old_slug != updated.get("slug"):
        redirects[f"produkt/{old_slug}"] = target
    for k in list(redirects.keys()):
        redirects[k] = target
    with open(redirects_path, "w", encoding="utf-8") as fh:
        json.dump(redirects, fh, ensure_ascii=False, indent=2)
    print("redirects_updated", len(redirects), "target=", target)
