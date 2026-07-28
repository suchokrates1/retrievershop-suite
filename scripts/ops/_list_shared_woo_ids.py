#!/usr/bin/env python3
"""List magazyn products that share the same woo_product_id."""
from __future__ import annotations

import os
from collections import defaultdict

os.environ["DISABLE_SCHEDULERS"] = "1"

from magazyn.db import configure_engine, get_session
from magazyn.models.products import Product
from magazyn.services.woo_product_naming import product_family_key


def main() -> int:
    configure_engine()
    with get_session() as db:
        by_woo: dict[int, list[Product]] = defaultdict(list)
        for p in db.query(Product).filter(Product.woo_product_id.isnot(None)).all():
            by_woo[int(p.woo_product_id)].append(p)
        shared = {wid: ps for wid, ps in by_woo.items() if len(ps) > 1}
        print(
            f"shared_woo_ids={len(shared)} "
            f"products_in_shared={sum(len(v) for v in shared.values())}"
        )
        for wid, ps in sorted(shared.items(), key=lambda kv: -len(kv[1])):
            colors = ", ".join(sorted({(p.color or "?") for p in ps}))
            fam = product_family_key(ps[0])
            print(
                f"woo={wid} n={len(ps)} fam={fam} "
                f"colors=[{colors}] ids={[p.id for p in ps]}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
