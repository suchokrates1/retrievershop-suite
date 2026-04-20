"""Test badge price dla oferty z aktywna kampania + analiza bledu 5zl."""
import sys
import asyncio
sys.path.insert(0, '/app')
from magazyn.factory import create_app
app = create_app()

with app.app_context():
    from magazyn.allegro_api.offers import get_offer_badge_price, get_offer_price
    from magazyn.scripts.price_checker_ws import check_offer_price, CDP_HOST, CDP_PORT, MAX_DELIVERY_DAYS

    # TEST 1: Oferta z aktywna kampania Allegro Days
    oid = "18334850404"
    print("=" * 100)
    print(f"TEST BADGE: Oferta {oid} (powinna miec kampanie)")
    print("=" * 100)

    base = get_offer_price(oid)
    badge = get_offer_badge_price(oid)

    base_price = float(base["price"]) if base.get("success") else None
    badge_float = float(badge) if badge else None
    effective = badge_float if badge_float else base_price

    print(f"  Cena bazowa (API):  {base_price}")
    print(f"  Cena badge:         {badge_float}")
    print(f"  Cena efektywna:     {effective}")

    if badge_float:
        print(f"  >>> KAMPANIA AKTYWNA: badge {badge_float} vs baza {base_price} (roznica: {base_price - badge_float:.2f}) <<<")

    # CDP test
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    result = loop.run_until_complete(
        check_offer_price(oid, "Szelki guard M fiolet", effective, CDP_HOST, CDP_PORT, MAX_DELIVERY_DAYS)
    )
    loop.close()

    print(f"\n  CDP success:    {result.success}")
    print(f"  CDP my_price:   {result.my_price}")
    print(f"  Pozycja:        {result.my_position}")
    comps = result.competitors or []
    print(f"  Konkurenci:     {len(comps)}")
    if result.cheapest_competitor:
        c = result.cheapest_competitor
        print(f"  Najtanszy:      {c.price} zl ({c.seller})")
        print(f"  Roznica:        {effective - c.price:+.2f} zl")

    # Pokaz wszystkich konkurentow
    print(f"\n  Lista wszystkich konkurentow (filtrowanych):")
    for i, c in enumerate(comps):
        print(f"    {i+1}. {c.price:.2f} zl | {c.seller} | url={c.offer_url or '-'}")

    print(f"\n{'='*100}")
    print("KONIEC")
