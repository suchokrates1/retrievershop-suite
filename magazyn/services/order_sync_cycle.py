"""Orkiestracja pojedynczego cyklu synchronizacji zamowien."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Optional


@dataclass(frozen=True)
class OrderSyncCallbacks:
    sync_from_allegro_events: Callable[[Any], dict]
    refresh_order_profit_cache: Callable[[Any], dict]
    sync_allegro_fulfillment: Callable[[Any], dict]
    process_pending_invoices: Callable[[], dict]
    cancel_stale_unpaid_orders: Callable[[], dict]
    get_last_offer_sync_date: Callable[[], Optional[str]]
    set_last_offer_sync_date: Callable[[str], None]


class OrderSyncCycle:
    def __init__(self, *, logger: logging.Logger, callbacks: OrderSyncCallbacks):
        self.logger = logger
        self.callbacks = callbacks

    def run(self, app: Any) -> None:
        with app.app_context():
            self.run_allegro_events_sync(app)
            self.run_parcel_tracking_sync()
            self.run_profit_cache_refresh(app)
            self.run_allegro_fulfillment_sync(app)
            self.run_returns_sync()
            self.run_invoice_processing()
            self.run_unpaid_auto_cancel()
            self.run_daily_offer_and_promo_sync()

    def run_allegro_events_sync(self, app: Any) -> None:
        self.logger.info("Starting Allegro Events sync")
        ev_stats = self.callbacks.sync_from_allegro_events(app)
        self.logger.info(
            f"Allegro Events sync completed: events={ev_stats['events_fetched']}, "
            f"synced={ev_stats['orders_synced']}, cancelled={ev_stats['orders_cancelled']}, "
            f"errors={ev_stats['errors']}"
        )

    def run_parcel_tracking_sync(self) -> None:
        from ..parcel_tracking import sync_parcel_statuses

        self.logger.info("Starting automatic parcel tracking sync")
        stats = sync_parcel_statuses()
        self.logger.info(
            f"Parcel tracking sync completed: checked={stats['checked']}, "
            f"updated={stats['updated']}, errors={stats['errors']}"
        )

    def run_profit_cache_refresh(self, app: Any) -> None:
        self.logger.info("Starting real profit cache refresh")
        profit_stats = self.callbacks.refresh_order_profit_cache(app)
        self.logger.info(
            f"Real profit cache refresh completed: checked={profit_stats['checked']}, "
            f"updated={profit_stats['updated']}, finalized={profit_stats['finalized']}, "
            f"pending={profit_stats['pending']}, errors={profit_stats['errors']}"
        )

    def run_allegro_fulfillment_sync(self, app: Any) -> None:
        self.logger.info("Starting Allegro fulfillment sync")
        f_stats = self.callbacks.sync_allegro_fulfillment(app)
        self.logger.info(
            f"Allegro fulfillment sync completed: checked={f_stats['checked']}, "
            f"updated={f_stats['updated']}, errors={f_stats['errors']}"
        )

    def run_returns_sync(self) -> None:
        from ..returns import sync_returns

        self.logger.info("Starting automatic returns sync")
        returns_stats = sync_returns()
        self.logger.info(f"Returns sync completed: {returns_stats}")

    def run_invoice_processing(self) -> None:
        try:
            inv_stats = self.callbacks.process_pending_invoices()
            if inv_stats["processed"] > 0:
                self.logger.info(
                    f"Invoice processing: processed={inv_stats['processed']}, "
                    f"success={inv_stats['success']}, errors={inv_stats['errors']}"
                )
        except Exception as inv_err:
            self.logger.error(f"Error in invoice processing: {inv_err}", exc_info=True)

    def run_unpaid_auto_cancel(self) -> None:
        try:
            cancel_stats = self.callbacks.cancel_stale_unpaid_orders()
            if cancel_stats["cancelled"] > 0:
                self.logger.info(
                    f"Unpaid auto-cancel: checked={cancel_stats['checked']}, "
                    f"cancelled={cancel_stats['cancelled']}, errors={cancel_stats['errors']}"
                )
        except Exception as cancel_err:
            self.logger.error(f"Error in unpaid auto-cancel: {cancel_err}", exc_info=True)

    def run_daily_allegro_offer_sync(self) -> None:
        from ..allegro_sync import sync_offers

        self.logger.info("Starting daily Allegro offer sync")
        offer_stats = sync_offers()
        self.logger.info(f"Daily offer sync completed: {offer_stats}")

    def run_daily_promo_sync(self) -> None:
        from .allegro_promotions import get_promotions_summary

        self.logger.info("Starting daily promo sync")
        promo_summary = get_promotions_summary()
        if promo_summary.error:
            self.logger.warning(f"Promo sync warning: {promo_summary.error}")
        else:
            self.logger.info(
                f"Promo sync completed: active={promo_summary.active_count}, "
                f"renewing_tomorrow={len(promo_summary.renewing_tomorrow)}"
            )

    def run_daily_offer_and_promo_sync(self) -> None:
        today = datetime.now().strftime("%Y-%m-%d")
        if self.callbacks.get_last_offer_sync_date() == today:
            self.logger.debug("Offer sync already done today, skipping")
            return

        try:
            self.run_daily_allegro_offer_sync()
            self.callbacks.set_last_offer_sync_date(today)
        except Exception as offer_err:
            self.logger.error(f"Error in daily offer sync: {offer_err}", exc_info=True)

        try:
            self.run_daily_promo_sync()
        except Exception as promo_err:
            self.logger.error(f"Error in promo sync: {promo_err}", exc_info=True)


__all__ = ["OrderSyncCallbacks", "OrderSyncCycle"]