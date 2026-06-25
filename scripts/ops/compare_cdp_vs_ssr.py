#!/usr/bin/env python3
"""Porownanie CDP (pelny dialog, VAT-exact) vs SSR HTTP (podsumowanie) na minipc.

Dla kazdej oferty:
- SSR: czas + najtanszy konkurent brutto + liczba ofert (podsumowanie z business.allegro.pl)
- CDP: czas + najtanszy konkurent brutto (po filtrze dostawy/wykluczen) + nasza pozycja

Uzycie: docker exec ... python3 /tmp/compare_cdp_vs_ssr.py 18675226204 18595218828 ...
"""

from __future__ import annotations

import asyncio
import sys
import time

from magazyn.services.allegro_price_scraper.checker import check_offer_price
from magazyn.services.allegro_price_scraper.config import CDP_HOST, CDP_PORT_PRICE_CHECK
from magazyn.services.allegro_price_scraper.http_offers import (
    cheapest_gross_from_snapshot,
    fetch_offer_ssr_snapshot,
)
from magazyn.services.allegro_price_scraper.session import fetch_allegro_session

OFFERS = sys.argv[1:] or ["18675226204", "18595218828", "18661454079"]


async def main(http) -> None:
    for offer_id in OFFERS:
        print(f"\n=== oferta {offer_id} ===")

        # --- SSR ---
        if http is not None:
            t0 = time.perf_counter()
            try:
                snap = fetch_offer_ssr_snapshot(offer_id, session=http)
                dt = time.perf_counter() - t0
                if snap:
                    cheapest = cheapest_gross_from_snapshot(snap)
                    sums = ", ".join(
                        f"{s.label}={s.gross_price} ({s.price_label})" for s in snap.summaries
                    )
                    print(f"SSR {dt:.2f}s: najtanszy_brutto={cheapest} ofert={snap.offer_count} | {sums}")
                else:
                    print(f"SSR {dt:.2f}s: brak danych (403/parsing)")
            except Exception as exc:
                print(f"SSR blad: {exc}")

        # --- CDP ---
        t0 = time.perf_counter()
        try:
            res = await check_offer_price(offer_id, cdp_host=CDP_HOST, cdp_port=CDP_PORT_PRICE_CHECK)
            dt = time.perf_counter() - t0
            cheapest = res.cheapest_competitor.price if res.cheapest_competitor else None
            seller = res.cheapest_competitor.seller if res.cheapest_competitor else "-"
            print(
                f"CDP {dt:.2f}s: success={res.success} source={res.source} "
                f"najtanszy_brutto={cheapest} ({seller}) "
                f"ofert={res.competitors_all_count} pozycja={res.my_position} err={res.error}"
            )
        except Exception as exc:
            print(f"CDP blad: {exc}")


if __name__ == "__main__":
    try:
        _http = fetch_allegro_session(CDP_HOST, CDP_PORT_PRICE_CHECK)
    except Exception as exc:
        _http = None
        print(f"[SSR] brak sesji HTTP: {exc}")
    asyncio.run(main(_http))
