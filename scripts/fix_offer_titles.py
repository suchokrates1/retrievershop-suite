#!/usr/bin/env python3
"""
Skrypt naprawiajacy literowki w tytulach ofert na Allegro.

Uzywa PATCH /sale/product-offers/{offerId} z polem "name".
Uruchamiac na serwerze produkcyjnym (minipc).
"""
import sys
import os
import time

# Dodaj sciezke do projektu
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from magazyn.allegro_api.offers import change_offer_name, get_offer_details


# Mapa: offer_id -> poprawiony tytul
# Oryginalne bledy -> poprawki:
#   Truelovr -> Truelove
#   Frone -> Front
#   pda Tuelove -> psa Truelove
#   czarneL -> czarne
#   pomaranczpwe -> pomaranczowe
#   psaTruelove -> psa Truelove
#   psaTrueLove -> psa TrueLove
TITLE_FIXES = {
    "18223994217": "Szelki dla psa Truelove Blossom XL czerwone",
    "17839093574": "Szelki dla psa Truelove Blossom XL czerwone",
    "18310841842": "Szelki dla psa Truelove Front Line Premium M r\u00f3\u017cowe",
    "18314591880": "Szelki dla psa Truelove Front Line Premium XS szare",
    "18334986880": "Szelki dla psa Truelove Security L czarne",
    "18290293154": "Szelki dla psa z lampk\u0105 LED Truelove Tracker L pomara\u0144czowe",
    "18352765719": "Szelki dla psa Truelove Lumen L czarne",
    "18334974372": "Szelki dla psa TrueLove Tropical M turkusowe",
}


def main():
    print("=" * 60)
    print("Naprawa literowek w tytulach ofert Allegro")
    print("=" * 60)

    success_count = 0
    error_count = 0

    for offer_id, new_title in TITLE_FIXES.items():
        print(f"\n--- Oferta {offer_id} ---")

        # Najpierw pobierz aktualny tytul
        details = get_offer_details(offer_id)
        if details.get("success"):
            current_title = details.get("title", "?")
            print(f"  Stary tytul: {current_title}")
            print(f"  Nowy tytul:  {new_title}")

            if current_title == new_title:
                print("  [POMINIETY] Tytul juz jest poprawny.")
                success_count += 1
                continue
        else:
            print(f"  [OSTRZEZENIE] Nie udalo sie pobrac szczegolow: {details.get('error')}")
            print(f"  Probuje zmienic tytul mimo to...")

        # Zmien tytul
        result = change_offer_name(offer_id, new_title)
        if result.get("success"):
            print("  [OK] Tytul zmieniony pomyslnie!")
            success_count += 1
        else:
            print(f"  [BLAD] {result.get('error')}")
            if result.get("details"):
                print(f"  Szczegoly: {result.get('details')}")
            error_count += 1

        # Przerwa miedzy requestami (rate limiting)
        time.sleep(1)

    print(f"\n{'=' * 60}")
    print(f"Podsumowanie: {success_count} sukcesow, {error_count} bledow")
    print(f"{'=' * 60}")

    return 0 if error_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
