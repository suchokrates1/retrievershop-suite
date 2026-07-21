#!/usr/bin/env python3
"""Fix bad ASCII slug for Chłodząca (ł stripped)."""
import os
os.environ.setdefault("DISABLE_SCHEDULERS", "1")
from magazyn.factory import create_app
from magazyn.woocommerce_api import WooClient

app = create_app()
with app.app_context():
    c = WooClient()
    # 5175 from merge log
    updated = c.put(
        "wp-json/wc/v3/products/5175",
        json={
            "name": "Kamizelka dla psa Truelove Chłodząca",
            "slug": "kamizelka-dla-psa-truelove-chlodzaca",
        },
    )
    print("slug=", updated.get("slug"), "name=", updated.get("name"))
