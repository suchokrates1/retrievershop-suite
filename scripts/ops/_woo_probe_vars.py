#!/usr/bin/env python3
import os
import json

os.environ.setdefault("DISABLE_SCHEDULERS", "1")
from magazyn.factory import create_app
from magazyn.woocommerce_api import WooClient

app = create_app()
with app.app_context():
    c = WooClient()
    vars_ = c.get("wp-json/wc/v3/products/3586/variations", params={"per_page": 5}) or []
    for v in vars_:
        print(json.dumps({
            "id": v.get("id"),
            "sku": v.get("sku"),
            "attrs": v.get("attributes"),
            "stock": v.get("stock_quantity"),
        }, ensure_ascii=False))
