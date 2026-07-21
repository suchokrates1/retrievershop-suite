#!/usr/bin/env python3
"""Scal kolory Woo: 1 parent na rodzine (category|brand|series).

Domyslnie dry-run. Apply: --apply
Pilot: --family "Szelki|Truelove|Front Line Premium"
Wszystkie rodziny z >1 kolorem: --all

Uruchomienie (lokalnie lub w kontenerze magazyn, NIE pytest):
  DISABLE_SCHEDULERS=1 PYTHONPATH=/app python scripts/ops/woo_merge_color_families.py --family "..."
  DISABLE_SCHEDULERS=1 PYTHONPATH=/app python scripts/ops/woo_merge_color_families.py --all --apply
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Optional

os.environ.setdefault("DISABLE_SCHEDULERS", "1")

from magazyn.db import get_session
from magazyn.factory import create_app
from magazyn.models.products import Product, ProductSize
from magazyn.services.woo_catalog_sync import _sync_one_family
from magazyn.services.woo_product_naming import canonical_woo_product_name, product_family_key
from magazyn.woocommerce_api import WooClient, WooClientError


@dataclass
class FamilyReport:
    key: tuple[str, str, str]
    products: list[Product] = field(default_factory=list)
    woo_ids: list[int] = field(default_factory=list)
    eans: list[str] = field(default_factory=list)
    colors: list[str] = field(default_factory=list)


def _parse_family(spec: str) -> tuple[str, str, str]:
    parts = [p.strip().lower() for p in spec.split("|")]
    if len(parts) != 3:
        raise SystemExit('family musi byc "Category|Brand|Series"')
    return parts[0], parts[1], parts[2]


def _load_families(
    db,
    *,
    family_filter: Optional[tuple[str, str, str]] = None,
    multi_color_only: bool = True,
) -> list[FamilyReport]:
    products = db.query(Product).all()
    by_key: dict[tuple[str, str, str], list[Product]] = defaultdict(list)
    for p in products:
        key = product_family_key(p)
        if not any(key):
            continue
        if family_filter and key != family_filter:
            continue
        by_key[key].append(p)

    reports: list[FamilyReport] = []
    for key, members in sorted(by_key.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        colors = sorted({(m.color or "").strip() for m in members if (m.color or "").strip()})
        if multi_color_only and len(colors) < 2 and not family_filter:
            continue
        woo_ids = sorted({int(m.woo_product_id) for m in members if m.woo_product_id})
        eans: list[str] = []
        for m in members:
            for size in db.query(ProductSize).filter(ProductSize.product_id == m.id).all():
                if size.barcode:
                    eans.append(size.barcode.strip())
        reports.append(
            FamilyReport(
                key=key,
                products=members,
                woo_ids=woo_ids,
                eans=eans,
                colors=colors,
            )
        )
    return reports


def _get_product_slug(client: WooClient, product_id: int) -> str:
    try:
        data = client.get(f"wp-json/wc/v3/products/{product_id}")
    except WooClientError:
        return ""
    return (data.get("slug") or "").strip()


def _set_product_status(client: WooClient, product_id: int, status: str) -> None:
    client.put(f"wp-json/wc/v3/products/{product_id}", json={"status": status})


def _variation_parent_id(client: WooClient, variation_id: int, fallback_parent: int) -> Optional[int]:
    try:
        data = client.get(f"wp-json/wc/v3/products/{fallback_parent}/variations/{variation_id}")
        if data and data.get("id"):
            return int(fallback_parent)
    except WooClientError:
        pass
    try:
        data = client.get(f"wp-json/wc/v3/products/{variation_id}")
    except WooClientError:
        return None
    if not data:
        return None
    if (data.get("type") or "").lower() == "variation":
        parent = data.get("parent_id") or data.get("parent")
        return int(parent) if parent else None
    return None


def _detach_foreign_variations(
    db,
    client: WooClient,
    report: FamilyReport,
    canonical_id: int,
) -> list[dict[str, Any]]:
    """Wyczysc mapowania wariantow lezacych na innym parentcie; usun SKU ze starych."""
    actions: list[dict[str, Any]] = []
    for product in report.products:
        sizes = db.query(ProductSize).filter(ProductSize.product_id == product.id).all()
        for size in sizes:
            if not size.woo_variation_id:
                continue
            var_id = int(size.woo_variation_id)
            parent = _variation_parent_id(client, var_id, int(product.woo_product_id or 0) or canonical_id)
            if parent and int(parent) == int(canonical_id):
                continue
            # Variation na obcym parentcie — zwolnij SKU i mapowanie
            if parent:
                try:
                    client.put(
                        f"wp-json/wc/v3/products/{parent}/variations/{var_id}",
                        json={"sku": "", "status": "private"},
                    )
                    actions.append({"cleared_sku": var_id, "old_parent": parent})
                except WooClientError as exc:
                    actions.append({"clear_sku_error": var_id, "error": str(exc)})
            size.woo_variation_id = None
            actions.append({"cleared_mapping": size.id, "ean": size.barcode})
    return actions


def _merge_family(
    db,
    client: WooClient,
    report: FamilyReport,
    *,
    apply: bool,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "family": "|".join(report.key),
        "colors": report.colors,
        "mag_products": [p.id for p in report.products],
        "old_woo_ids": report.woo_ids,
        "redirects": {},
        "canonical_woo_id": None,
        "applied": False,
    }
    if not report.products:
        return result

    old_slugs: dict[int, str] = {}
    for wid in report.woo_ids:
        slug = _get_product_slug(client, wid)
        if slug:
            old_slugs[wid] = slug

    counts: dict[int, int] = defaultdict(int)
    for p in report.products:
        if p.woo_product_id:
            counts[int(p.woo_product_id)] += 1
    elect = max(counts.items(), key=lambda kv: (kv[1], kv[0]))[0] if counts else None

    if not apply:
        result["would_elect"] = elect
        result["stats_dry"] = {
            "members": len(report.products),
            "colors": len(report.colors),
            "eans": len(report.eans),
            "name": canonical_woo_product_name(report.products[0]),
            "old_slugs": old_slugs,
        }
        return result

    if elect:
        for p in report.products:
            p.woo_product_id = elect
        result["detach"] = _detach_foreign_variations(db, client, report, int(elect))

    stats = {"products": 0, "variations": 0, "errors": 0, "skipped": 0}
    _sync_one_family(
        db,
        client,
        report.products,
        refresh_content=False,
        stats=stats,
    )
    db.flush()
    result["applied"] = True

    canonical = report.products[0].woo_product_id
    result["canonical_woo_id"] = canonical
    result["stats"] = stats

    for wid in report.woo_ids:
        if canonical and int(wid) != int(canonical):
            try:
                _set_product_status(client, int(wid), "private")
                result.setdefault("privatized", []).append(int(wid))
            except WooClientError as exc:
                result.setdefault("privatize_errors", []).append(
                    {"id": int(wid), "error": str(exc)}
                )

    new_slug = _get_product_slug(client, int(canonical)) if canonical else ""
    # Kanoniczny slug z nazwy modelu (bez koloru/rozmiaru w URL)
    desired_slug = ""
    try:
        from magazyn.services.woo_product_naming import sanitize_parent_product_title
        import re
        import unicodedata

        def _slugify(text: str) -> str:
            normalized = unicodedata.normalize("NFKD", text)
            ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
            return re.sub(r"[^a-zA-Z0-9]+", "-", ascii_text.lower()).strip("-")

        desired_name = canonical_woo_product_name(report.products[0])
        desired_slug = _slugify(desired_name)
        if desired_slug and new_slug != desired_slug:
            updated = client.put(
                f"wp-json/wc/v3/products/{int(canonical)}",
                json={"name": desired_name, "slug": desired_slug},
            )
            new_slug = (updated.get("slug") or desired_slug).strip()
            result["renamed_slug"] = new_slug
    except Exception as exc:  # noqa: BLE001
        result["rename_error"] = str(exc)

    if new_slug:
        target = f"/produkt/{new_slug}/"
        for wid, slug in old_slugs.items():
            if slug and slug != new_slug:
                result["redirects"][f"produkt/{slug}"] = target
        if desired_slug and old_slugs:
            # redirect previous elect slug if renamed
            pass

    return result


def _print_inventory(reports: list[FamilyReport]) -> None:
    print(f"families={len(reports)}")
    for r in reports:
        print(
            f"  {'|'.join(r.key)} colors={len(r.colors)} "
            f"products={len(r.products)} woo_ids={r.woo_ids} eans={len(r.eans)} "
            f"color_list={r.colors}"
        )


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--family", help='Np. "Szelki|Truelove|Front Line Premium"')
    parser.add_argument("--all", action="store_true", help="Wszystkie rodziny multi-color")
    parser.add_argument("--apply", action="store_true", help="Wykonaj zmiany (domyslnie dry-run)")
    parser.add_argument(
        "--redirects-out",
        default="",
        help="Zapisz mape 301 JSON (sciezka pliku)",
    )
    args = parser.parse_args(argv)

    if not args.family and not args.all:
        parser.error("podaj --family lub --all")

    family_filter = _parse_family(args.family) if args.family else None
    app = create_app()
    redirects: dict[str, str] = {}
    results: list[dict[str, Any]] = []

    with app.app_context():
        client = WooClient()
        with get_session() as db:
            reports = _load_families(
                db,
                family_filter=family_filter,
                multi_color_only=not bool(family_filter),
            )
            if not reports:
                print("brak rodzin do scalenia")
                return 1
            _print_inventory(reports)
            mode = "APPLY" if args.apply else "DRY-RUN"
            print(f"mode={mode}")
            for report in reports:
                res = _merge_family(db, client, report, apply=args.apply)
                results.append(res)
                redirects.update(res.get("redirects") or {})
                print(json.dumps(res, ensure_ascii=False, default=str))
            if args.apply:
                db.commit()
            else:
                db.rollback()

    if args.redirects_out:
        path = args.redirects_out
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(redirects, fh, ensure_ascii=False, indent=2)
        print(f"redirects_written={path} count={len(redirects)}")
    elif redirects:
        print("redirects=" + json.dumps(redirects, ensure_ascii=False))

    print(f"done families={len(results)} apply={args.apply}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
