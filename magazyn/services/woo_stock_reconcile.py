"""Reconcile stanow i deduplikacja SKU Woo vs magazyn (magazyn = SoT)."""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Optional

from ..db import get_session
from ..models.products import Product, ProductSize
from ..woocommerce_api import WooClient, WooClientError

logger = logging.getLogger(__name__)


def _stock_status(qty: int) -> str:
    return "instock" if qty > 0 else "outofstock"


def _set_variation_stock(
    client: WooClient,
    *,
    parent_id: int,
    variation_id: int,
    quantity: int,
    sku: str = "",
    size: str = "",
    dry_run: bool,
) -> None:
    if dry_run:
        return
    payload: dict[str, Any] = {
        "manage_stock": True,
        "stock_quantity": max(0, int(quantity)),
        "stock_status": _stock_status(quantity),
        "status": "publish",
    }
    if sku:
        payload["sku"] = sku
    if size:
        payload["attributes"] = [{"name": "Rozmiar", "option": size}]
    client.put(
        f"wp-json/wc/v3/products/{parent_id}/variations/{variation_id}",
        json=payload,
    )


def _hide_variation(
    client: WooClient,
    *,
    parent_id: int,
    variation_id: int,
    dry_run: bool,
) -> None:
    if dry_run:
        return
    client.put(
        f"wp-json/wc/v3/products/{parent_id}/variations/{variation_id}",
        json={
            "manage_stock": True,
            "stock_quantity": 0,
            "stock_status": "outofstock",
            "status": "private",
        },
    )


def _hide_product(client: WooClient, product_id: int, *, dry_run: bool) -> None:
    if dry_run:
        return
    client.put(
        f"wp-json/wc/v3/products/{product_id}",
        json={
            "manage_stock": True,
            "stock_quantity": 0,
            "stock_status": "outofstock",
            "status": "private",
        },
    )


def _index_woo_by_sku(client: WooClient) -> dict[str, list[dict[str, Any]]]:
    """Mapa SKU -> lista rekordow {parent_id, variation_id|None, type, status, qty}."""
    index: dict[str, list[dict[str, Any]]] = defaultdict(list)
    page = 1
    while page <= 50:
        products = client.get(
            "wp-json/wc/v3/products",
            params={"per_page": 100, "page": page, "status": "any"},
        ) or []
        if not products:
            break
        for product in products:
            pid = int(product["id"])
            ptype = (product.get("type") or "").lower()
            sku = (product.get("sku") or "").strip()
            if ptype == "simple" and sku:
                index[sku].append(
                    {
                        "parent_id": pid,
                        "variation_id": None,
                        "product_id": pid,
                        "type": "simple",
                        "status": product.get("status"),
                        "qty": product.get("stock_quantity"),
                    }
                )
            if ptype == "variation":
                # orphan / mislisted as top-level
                parent = int(product.get("parent_id") or 0)
                if sku:
                    index[sku].append(
                        {
                            "parent_id": parent,
                            "variation_id": pid,
                            "product_id": pid,
                            "type": "variation",
                            "status": product.get("status"),
                            "qty": product.get("stock_quantity"),
                            "orphan": parent <= 0,
                        }
                    )
            if ptype == "variable":
                vpage = 1
                while vpage <= 20:
                    variations = client.get(
                        f"wp-json/wc/v3/products/{pid}/variations",
                        params={"per_page": 100, "page": vpage},
                    ) or []
                    if not variations:
                        break
                    for var in variations:
                        vsku = (var.get("sku") or "").strip()
                        if not vsku:
                            continue
                        index[vsku].append(
                            {
                                "parent_id": pid,
                                "variation_id": int(var["id"]),
                                "product_id": int(var["id"]),
                                "type": "variation",
                                "status": var.get("status"),
                                "qty": var.get("stock_quantity"),
                                "orphan": False,
                            }
                        )
                    if len(variations) < 100:
                        break
                    vpage += 1
        if len(products) < 100:
            break
        page += 1
    return index


def reconcile_woo_stock(*, dry_run: bool = False) -> dict[str, int]:
    """Ujednolic stany Woo z magazynem i schowaj duplikaty/sieroty (private)."""
    stats = {
        "updated": 0,
        "deduped": 0,
        "orphaned": 0,
        "remapped": 0,
        "errors": 0,
        "mag_skus": 0,
        "woo_skus": 0,
    }
    try:
        client = WooClient()
    except WooClientError as exc:
        logger.error("Woo reconcile: %s", exc)
        return {**stats, "errors": 1}

    try:
        woo_index = _index_woo_by_sku(client)
    except Exception:
        logger.exception("Woo reconcile: blad indeksowania SKU")
        return {**stats, "errors": 1}

    stats["woo_skus"] = len(woo_index)
    seen_woo_keys: set[tuple[int, int | None]] = set()

    with get_session() as db:
        sizes = (
            db.query(ProductSize)
            .filter(ProductSize.barcode.isnot(None), ProductSize.barcode != "")
            .all()
        )
        stats["mag_skus"] = len(sizes)

        for size in sizes:
            sku = (size.barcode or "").strip()
            if not sku:
                continue
            qty = int(size.quantity or 0)
            hits = list(woo_index.get(sku) or [])

            # Preferuj zmapowany wariant
            preferred: Optional[dict[str, Any]] = None
            if size.woo_variation_id:
                for hit in hits:
                    if hit.get("variation_id") == int(size.woo_variation_id):
                        preferred = hit
                        break
            if preferred is None and hits:
                # Prefer non-orphan variation, then any
                non_orphan = [h for h in hits if not h.get("orphan")]
                preferred = (non_orphan or hits)[0]

            if preferred is None:
                continue

            # Remap parent/variation jesli potrzeba
            parent_id = int(preferred.get("parent_id") or 0)
            var_id = preferred.get("variation_id")
            if preferred.get("orphan") or parent_id <= 0:
                try:
                    _hide_product(client, int(preferred["product_id"]), dry_run=dry_run)
                    stats["orphaned"] += 1
                    if size.product and size.product.woo_product_id == preferred["product_id"]:
                        size.product.woo_product_id = None
                    if size.woo_variation_id == preferred.get("variation_id"):
                        size.woo_variation_id = None
                    stats["remapped"] += 1
                except Exception:
                    logger.exception("Woo reconcile orphan hide failed sku=%s", sku)
                    stats["errors"] += 1
                continue

            if size.product and size.product.woo_product_id != parent_id:
                size.product.woo_product_id = parent_id
                stats["remapped"] += 1
            if var_id and size.woo_variation_id != int(var_id):
                size.woo_variation_id = int(var_id)
                stats["remapped"] += 1

            try:
                if var_id:
                    _set_variation_stock(
                        client,
                        parent_id=parent_id,
                        variation_id=int(var_id),
                        quantity=qty,
                        sku=sku,
                        size=size.size or "",
                        dry_run=dry_run,
                    )
                    seen_woo_keys.add((parent_id, int(var_id)))
                else:
                    # simple product
                    if not dry_run:
                        client.put(
                            f"wp-json/wc/v3/products/{parent_id}",
                            json={
                                "manage_stock": True,
                                "stock_quantity": qty,
                                "stock_status": _stock_status(qty),
                                "status": "publish",
                            },
                        )
                    seen_woo_keys.add((parent_id, None))
                stats["updated"] += 1
            except Exception:
                logger.exception("Woo reconcile update failed sku=%s", sku)
                stats["errors"] += 1
                continue

            # Duplikaty tego samego SKU — ukryj
            for hit in hits:
                key = (
                    int(hit.get("parent_id") or hit["product_id"]),
                    int(hit["variation_id"]) if hit.get("variation_id") else None,
                )
                pref_key = (parent_id, int(var_id) if var_id else None)
                if key == pref_key:
                    continue
                try:
                    if hit.get("variation_id") and hit.get("parent_id"):
                        _hide_variation(
                            client,
                            parent_id=int(hit["parent_id"]),
                            variation_id=int(hit["variation_id"]),
                            dry_run=dry_run,
                        )
                    else:
                        _hide_product(client, int(hit["product_id"]), dry_run=dry_run)
                    stats["deduped"] += 1
                    seen_woo_keys.add(key)
                except Exception:
                    logger.exception("Woo reconcile dedupe failed sku=%s hit=%s", sku, hit)
                    stats["errors"] += 1

        # Wyczysc zduplikowane / osierocone mapowania variation:
        # zostaw woo_variation_id tylko na rozmiarze z matching barcode.
        owned_vids: dict[int, int] = {}
        for size in sizes:
            sku = (size.barcode or "").strip()
            if not sku or not size.woo_variation_id:
                continue
            owned_vids[int(size.woo_variation_id)] = int(size.id)

        stale = (
            db.query(ProductSize)
            .filter(ProductSize.woo_variation_id.isnot(None))
            .all()
        )
        for size in stale:
            vid = int(size.woo_variation_id)
            owner_id = owned_vids.get(vid)
            sku = (size.barcode or "").strip()
            if owner_id is not None and int(size.id) != owner_id:
                size.woo_variation_id = None
                stats["remapped"] += 1
            elif owner_id is None and not sku:
                # Brak barcode i nikt nie posiada tego vid po EAN
                size.woo_variation_id = None
                stats["remapped"] += 1

        db.commit()

    # Woo SKU bez odpowiednika w magazynie
    mag_skus = set()
    with get_session() as db:
        for row in db.query(ProductSize.barcode).filter(
            ProductSize.barcode.isnot(None), ProductSize.barcode != ""
        ):
            mag_skus.add((row[0] or "").strip())

    for sku, hits in woo_index.items():
        if sku in mag_skus:
            continue
        for hit in hits:
            try:
                if hit.get("orphan") or not hit.get("parent_id"):
                    _hide_product(client, int(hit["product_id"]), dry_run=dry_run)
                    stats["orphaned"] += 1
                elif hit.get("variation_id"):
                    _hide_variation(
                        client,
                        parent_id=int(hit["parent_id"]),
                        variation_id=int(hit["variation_id"]),
                        dry_run=dry_run,
                    )
                    stats["orphaned"] += 1
                else:
                    _hide_product(client, int(hit["product_id"]), dry_run=dry_run)
                    stats["orphaned"] += 1
            except Exception:
                logger.exception("Woo reconcile hide unknown sku=%s", sku)
                stats["errors"] += 1

    logger.info("Woo stock reconcile dry_run=%s stats=%s", dry_run, stats)
    return stats


__all__ = ["reconcile_woo_stock"]
