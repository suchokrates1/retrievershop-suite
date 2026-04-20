"""Test oferty 18317035085 - szelki treningowe Truelove czerwone L."""
import asyncio
import sys
sys.path.insert(0, '/app')
from magazyn.scripts.price_checker_ws import check_offer_price, print_result, MY_SELLER

async def test():
    print(f"MY_SELLER = '{MY_SELLER}'")
    
    result = await check_offer_price(
        offer_id='18317035085',
        title='Szelki treningowe Truelove czerwone regulowane L odblaskowe',
        my_price=217.00,
        cdp_host='192.168.128.7',
        cdp_port=9223
    )
    print_result(result)
    
    print(f'\n--- NASZE INNE OFERTY W DIALOGU (our_other_offers) ---')
    if result.our_other_offers:
        for o in result.our_other_offers:
            print(f'  offer_id={o.offer_id} | cena={o.price:.2f} zl | seller={o.seller}')
    else:
        print('  (brak)')
    
    print(f'\nKonkurenci ({len(result.competitors or [])}):')
    for c in (result.competitors or []):
        print(f'  [{c.seller}] {c.price:.2f} zl | offerId={c.offer_id} | is_mine={c.is_mine}')

asyncio.run(test())
