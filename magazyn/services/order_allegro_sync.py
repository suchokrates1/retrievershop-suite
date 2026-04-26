"""Reczny sync zamowien z Allegro REST API."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import or_

from ..models import Order


@dataclass(frozen=True)
class ManualAllegroSyncResult:
    synced: int
    updated: int
    skipped: int
    total: int

    @property
    def message(self) -> str:
        return (
            f"Allegro API: {self.synced} nowych, {self.updated} zaktualizowanych, "
            f"{self.skipped} pominieto (laczne: {self.total} z API)"
        )


def sync_orders_from_allegro_api(
    db,
    *,
    sync_order_from_data: Callable,
    add_order_status: Callable,
    logger: logging.Logger | None = None,
) -> ManualAllegroSyncResult:
    from ..allegro_api.orders import (
        fetch_all_allegro_orders,
        get_allegro_internal_status,
        parse_allegro_order_to_data,
    )

    log = logger or logging.getLogger(__name__)
    checkout_forms = fetch_all_allegro_orders()
    synced = 0
    updated = 0
    skipped = 0

    for checkout_form in checkout_forms:
        try:
            order_data = parse_allegro_order_to_data(checkout_form)
            checkout_form_id = checkout_form.get("id", "")
            existing = (
                db.query(Order)
                .filter(
                    or_(
                        Order.external_order_id == checkout_form_id,
                        Order.order_id == f"allegro_{checkout_form_id}",
                    )
                )
                .first()
            )

            internal_status = get_allegro_internal_status(order_data)
            allegro_status = order_data.get("_allegro_status", "")
            fulfillment = order_data.get("_allegro_fulfillment_status", "")

            if existing:
                if not existing.user_login and order_data.get("user_login"):
                    existing.user_login = order_data["user_login"]
                if not existing.email and order_data.get("email"):
                    existing.email = order_data["email"]
                if not existing.phone and order_data.get("phone"):
                    existing.phone = order_data["phone"]
                if not existing.external_order_id:
                    existing.external_order_id = checkout_form_id

                added = add_order_status(
                    db,
                    existing.order_id,
                    internal_status,
                    notes=(
                        "Aktualizacja z Allegro API "
                        f"(status: {allegro_status}, fulfillment: {fulfillment})"
                    ),
                )
                if added:
                    log.info(
                        "Zaktualizowano status %s -> %s (fulfillment: %s)",
                        existing.order_id[:30],
                        internal_status,
                        fulfillment,
                    )
                updated += 1
            else:
                sync_order_from_data(db, order_data)
                add_order_status(
                    db,
                    order_data["order_id"],
                    internal_status,
                    notes=(
                        "Zsynchronizowano z Allegro API "
                        f"(status: {allegro_status}, fulfillment: {fulfillment})"
                    ),
                )
                synced += 1
        except Exception as exc:
            log.warning(
                "Blad przetwarzania zamowienia Allegro %s: %s",
                checkout_form.get("id", "?"),
                exc,
            )
            skipped += 1

    db.commit()
    return ManualAllegroSyncResult(
        synced=synced,
        updated=updated,
        skipped=skipped,
        total=len(checkout_forms),
    )


__all__ = ["ManualAllegroSyncResult", "sync_orders_from_allegro_api"]