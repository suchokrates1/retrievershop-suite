"""
Test E2E price checkera - 10 ofert z roznymi kategoriami.
Sprawdza pelny flow: badge API -> CDP scraping -> porownanie wynikow.
Przerwa 60s miedzy ofertami.
"""
import sys
import time
import asyncio
import json
import logging

sys.path.insert(0, '/app')

from magazyn.factory import create_app

app = create_app()

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('e2e_test')

# 10 wybranych ofert
TEST_OFFERS = [
    {"offer_id": "18295920735", "price": 230.00, "cat": "szelki",  "title": "Szelki guard dla sredniego psa Truelove Front Line Premium M brazowe"},
    {"offer_id": "18314317012", "price": 113.00, "cat": "smycz",   "title": "SMYCZ DLA PSA Z AMORTYZATOREM TRUELOVE ADVENTURE 160CM CZARNA M"},
    {"offer_id": "18363853222", "price": 90.00,  "cat": "pas",     "title": "Pas samochodowy dla psa Truelove Premium stalowy roz"},
    {"offer_id": "18338418066", "price": 67.00,  "cat": "obroza1", "title": "Obroza dla psa Truelove Active XL czarna"},
    {"offer_id": "18314173884", "price": 79.00,  "cat": "obroza2", "title": "Obroza dla psa Truelove Tropical XXL"},
    {"offer_id": "18432311394", "price": 61.00,  "cat": "obroza3", "title": "Obroza dla psa materialowa odblaskowa Truelove Active M czerwona"},
    {"offer_id": "18390950619", "price": 80.00,  "cat": "obroza4", "title": "Obroza dla psa materialowa odblaskowa Truelove Tropical XL"},
    {"offer_id": "18377799508", "price": 67.00,  "cat": "obroza5", "title": "Obroza dla psa materialowa odblaskowa Truelove Active 2XL czerwona"},
    {"offer_id": "18314181819", "price": 80.00,  "cat": "obroza6", "title": "Obroza dla psa materialowa odblaskowa Truelove Tropical XL"},
    {"offer_id": "18377812970", "price": 67.00,  "cat": "obroza7", "title": "Obroza dla psa materialowa odblaskowa Truelove Active M czerwona"},
]

DELAY_BETWEEN = 65  # sekundy miedzy ofertami


def test_badge_api(offer_id):
    """Krok 1: Sprawdz badge price z API."""
    from magazyn.allegro_api.offers import get_offer_badge_price, get_offer_price
    
    # Cena bazowa z API
    base_result = get_offer_price(offer_id)
    base_price = float(base_result["price"]) if base_result.get("success") and base_result.get("price") else None
    
    # Cena badge (kampanie)
    badge_price = get_offer_badge_price(offer_id)
    badge_float = float(badge_price) if badge_price else None
    
    return {
        "base_price": base_price,
        "badge_price": badge_float,
        "effective_price": badge_float if badge_float else base_price,
    }


def test_cdp_scraping(offer_id, title, my_price):
    """Krok 2: Przejdz przez CDP scraper (pelny flow)."""
    from magazyn.scripts.price_checker_ws import check_offer_price, CDP_HOST, CDP_PORT, MAX_DELIVERY_DAYS
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = loop.run_until_complete(
            check_offer_price(offer_id, title, my_price, CDP_HOST, CDP_PORT, MAX_DELIVERY_DAYS)
        )
    finally:
        loop.close()
    
    return {
        "success": result.success,
        "error": result.error,
        "my_price": result.my_price,
        "my_position": result.my_position,
        "competitors_count": len(result.competitors) if result.competitors else 0,
        "competitors_all_count": result.competitors_all_count,
        "cheapest_price": result.cheapest_competitor.price if result.cheapest_competitor else None,
        "cheapest_seller": result.cheapest_competitor.seller if result.cheapest_competitor else None,
        "cheapest_url": result.cheapest_competitor.offer_url if result.cheapest_competitor else None,
        "cheapest_is_super": getattr(result.cheapest_competitor, 'is_super_seller', None) if result.cheapest_competitor else None,
    }


def test_full_flow(offer_id, title, db_price):
    """Krok 3: Pelny flow jak w check_single_offer (badge + CDP)."""
    from magazyn.allegro_api.offers import get_offer_badge_price
    
    badge_price = get_offer_badge_price(offer_id)
    effective_price = float(badge_price) if badge_price else db_price
    
    cdp = test_cdp_scraping(offer_id, title, effective_price)
    
    return effective_price, cdp


with app.app_context():
    results = []
    
    print("=" * 120)
    print("TEST E2E PRICE CHECKER - 10 ofert")
    print("=" * 120)
    
    for i, offer in enumerate(TEST_OFFERS):
        oid = offer["offer_id"]
        print(f"\n{'='*120}")
        print(f"[{i+1}/10] {offer['cat'].upper()} | Oferta {oid} | Cena DB: {offer['price']} zl")
        print(f"  Tytul: {offer['title']}")
        print(f"{'='*120}")
        
        # KROK 1: Badge API
        print(f"\n  --- KROK 1: Badge API ---")
        api_result = test_badge_api(oid)
        print(f"  Cena bazowa (API):  {api_result['base_price']}")
        print(f"  Cena badge:         {api_result['badge_price']}")
        print(f"  Cena efektywna:     {api_result['effective_price']}")
        
        has_badge = api_result['badge_price'] is not None
        
        # KROK 2: Pelny flow (badge + CDP)
        print(f"\n  --- KROK 2: Pelny flow (badge + CDP scraping) ---")
        effective_price, cdp = test_full_flow(oid, offer['title'], offer['price'])
        
        print(f"  Cena uzyta (effective): {effective_price}")
        print(f"  CDP success:            {cdp['success']}")
        if cdp['error']:
            print(f"  CDP error:              {cdp['error']}")
        print(f"  CDP my_price:           {cdp['my_price']}")
        print(f"  Pozycja:                {cdp['my_position']}")
        print(f"  Konkurenci (filtr):     {cdp['competitors_count']}")
        print(f"  Konkurenci (all):       {cdp['competitors_all_count']}")
        
        if cdp['cheapest_price']:
            diff = effective_price - cdp['cheapest_price']
            print(f"  Najtanszy:              {cdp['cheapest_price']} zl ({cdp['cheapest_seller']})")
            print(f"  SuperSeller:            {cdp['cheapest_is_super']}")
            print(f"  Roznica:                {diff:+.2f} zl")
            if diff > 0:
                status = "DROZSI"
            elif diff < 0:
                status = "TANSI"
            else:
                status = "ROWNI"
        else:
            status = "BRAK KONKURENCJI"
            diff = None
        
        print(f"\n  >>> STATUS: {status} <<<")
        if has_badge:
            print(f"  >>> KAMPANIA AKTYWNA - cena badge {api_result['badge_price']} vs bazowa {api_result['base_price']} <<<")
        
        results.append({
            "nr": i + 1,
            "offer_id": oid,
            "cat": offer['cat'],
            "db_price": offer['price'],
            "api_base": api_result['base_price'],
            "api_badge": api_result['badge_price'],
            "effective": effective_price,
            "cdp_ok": cdp['success'],
            "cdp_my_price": cdp['my_price'],
            "position": cdp['my_position'],
            "competitors": cdp['competitors_count'],
            "competitors_all": cdp['competitors_all_count'],
            "cheapest": cdp['cheapest_price'],
            "cheapest_seller": cdp['cheapest_seller'],
            "status": status,
        })
        
        # Przerwa miedzy ofertami (oprócz ostatniej)
        if i < len(TEST_OFFERS) - 1:
            print(f"\n  Czekam {DELAY_BETWEEN}s przed nastepna oferta...")
            time.sleep(DELAY_BETWEEN)
    
    # PODSUMOWANIE
    print(f"\n\n{'='*120}")
    print("PODSUMOWANIE TESTU E2E")
    print(f"{'='*120}")
    print(f"{'Nr':<4} {'Kat':<10} {'OfferID':<14} {'DB':<8} {'API':<8} {'Badge':<8} {'Efekt.':<8} {'CDPok':<6} {'Poz':<4} {'Konk':<5} {'Najtan':<8} {'Status':<18}")
    print("-" * 120)
    for r in results:
        badge_str = f"{r['api_badge']:.2f}" if r['api_badge'] else "-"
        cheapest_str = f"{r['cheapest']:.2f}" if r['cheapest'] else "-"
        pos_str = str(r['position']) if r['position'] else "-"
        api_str = f"{r['api_base']:.2f}" if r['api_base'] else "ERR"
        eff_str = f"{r['effective']:.2f}"
        print(f"{r['nr']:<4} {r['cat']:<10} {r['offer_id']:<14} {r['db_price']:<8.2f} {api_str:<8} {badge_str:<8} {eff_str:<8} {str(r['cdp_ok']):<6} {pos_str:<4} {r['competitors']:<5} {cheapest_str:<8} {r['status']:<18}")
    
    # Stats
    ok_count = sum(1 for r in results if r['cdp_ok'])
    badge_count = sum(1 for r in results if r['api_badge'])
    cheaper = sum(1 for r in results if r['status'] == 'TANSI')
    pricier = sum(1 for r in results if r['status'] == 'DROZSI')
    
    print(f"\n  CDP OK: {ok_count}/{len(results)}")
    print(f"  Z kampania (badge): {badge_count}/{len(results)}")
    print(f"  Tansi: {cheaper}, Drozsi: {pricier}, Brak konkurencji: {sum(1 for r in results if r['status'] == 'BRAK KONKURENCJI')}")
    print(f"\nTest zakonczony.")
