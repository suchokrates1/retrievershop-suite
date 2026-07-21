#!/usr/bin/env python3
"""Export canonical woo_product_id per family from magazyn."""
import json
import os
from collections import defaultdict

os.environ.setdefault("DISABLE_SCHEDULERS", "1")
from magazyn.db import get_session
from magazyn.factory import create_app
from magazyn.models.products import Product
from magazyn.services.woo_product_naming import product_family_key

app = create_app()
with app.app_context():
    with get_session() as db:
        by = defaultdict(list)
        for p in db.query(Product).all():
            if p.woo_product_id:
                by[product_family_key(p)].append(int(p.woo_product_id))
        canon = {}
        for key, ids in by.items():
            # majority vote
            counts = defaultdict(int)
            for i in ids:
                counts[i] += 1
            best = max(counts.items(), key=lambda kv: (kv[1], kv[0]))[0]
            canon["|".join(key)] = best
        print(json.dumps({"canonical_ids": sorted(set(canon.values())), "by_family": canon}, ensure_ascii=False, indent=2))
        with open("/tmp/rs_canonical_woo_ids.json", "w", encoding="utf-8") as fh:
            json.dump({"canonical_ids": sorted(set(canon.values()))}, fh)
        print("written", len(set(canon.values())))
