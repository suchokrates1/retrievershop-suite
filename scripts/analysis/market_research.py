"""
Analiza rynkowa Allegro - akcesoria dla psow i produkty Truelove.

Wyszukuje produkty na Allegro przez API /offers/listing,
analizuje ceny, konkurencje i identyfikuje mozliwosci rynkowe.

Uruchamiac wewnatrz kontenera:
  flask shell < scripts/analysis/market_research.py

Lub przez docker exec:
  docker exec -i retrievershop-suite-magazyn_app-1 flask shell < scripts/analysis/market_research.py
"""
import json
import sys
import time
from collections import Counter, defaultdict

import requests

from magazyn.settings_store import settings_store
from magazyn.allegro_api.core import API_BASE_URL, _request_with_retry

# --- Konfiguracja wyszukiwan ---
SEARCH_QUERIES = {
    # Produkty Truelove - szukamy czego jeszcze mozna sprzedawac
    "truelove_szelki": "szelki truelove",
    "truelove_smycz": "smycz truelove",
    "truelove_obroza": "obroza truelove",
    "truelove_kamizelka": "kamizelka truelove",
    "truelove_uprząż": "uprząż truelove",
    "truelove_plecak": "plecak truelove pies",
    "truelove_buty": "buty truelove pies",
    "truelove_miska": "miska truelove",
    "truelove_legowisko": "legowisko truelove",
    "truelove_zabawka": "zabawka truelove pies",
    "truelove_general": "truelove pies",
    # Rynek ogolny - kategorie konkurencyjne
    "szelki_pies": "szelki dla psa",
    "szelki_antyuciagowe": "szelki antyuciagowe pies",
    "smycz_pies": "smycz dla psa",
    "obroza_pies": "obroza dla psa",
    "akcesoria_pies_spacer": "akcesoria pies spacer",
    "peleryna_pies": "peleryna przeciwdeszczowa pies",
    "kamizelka_pies": "kamizelka odblaskowa pies",
}


def search_allegro_listing(phrase, max_pages=3):
    """Wyszukaj produkty na Allegro i zwroc pelne dane ofert."""
    token = settings_store.get("ALLEGRO_ACCESS_TOKEN")
    if not token:
        print("BLAD: Brak tokenu Allegro!", file=sys.stderr)
        return []

    all_offers = []
    page = 1

    while page <= max_pages:
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.allegro.public.v1+json",
        }
        params = {"phrase": phrase, "page": page}

        try:
            response = _request_with_retry(
                requests.get,
                f"{API_BASE_URL}/offers/listing",
                endpoint="market-research",
                headers=headers,
                params=params,
            )
            data = response.json()
        except Exception as exc:
            print(f"  Blad wyszukiwania '{phrase}' strona {page}: {exc}", file=sys.stderr)
            break

        items = data.get("items", {})
        page_offers = []
        if isinstance(items, dict):
            for key in ("promoted", "regular"):
                for offer in items.get(key, []):
                    page_offers.append(_extract_offer_data(offer))
        elif isinstance(items, list):
            for offer in items:
                page_offers.append(_extract_offer_data(offer))

        all_offers.extend(page_offers)

        # Sprawdz nastepna strone
        next_link = data.get("links", {}).get("next")
        if not next_link or len(page_offers) == 0:
            break

        page += 1
        time.sleep(0.3)  # Rate limiting

    return all_offers


def _extract_offer_data(offer):
    """Wyciagnij kluczowe dane z oferty listingowej."""
    selling_mode = offer.get("sellingMode", {})
    price = selling_mode.get("price", {})
    seller = offer.get("seller", {})
    delivery = offer.get("delivery", {})
    category = offer.get("category", {})

    return {
        "id": offer.get("id"),
        "name": offer.get("name", ""),
        "price": float(price.get("amount", 0)) if price.get("amount") else None,
        "currency": price.get("currency", "PLN"),
        "seller_id": seller.get("id"),
        "seller_login": seller.get("login", ""),
        "seller_superSeller": seller.get("superSeller", False),
        "category_id": category.get("id"),
        "delivery_lowest_price": None,
        "promotion": offer.get("promotion", {}),
        "stock_available": offer.get("stock", {}).get("available"),
    }

    # Dostawa
    lowest = delivery.get("lowestPrice", {})
    if lowest:
        try:
            result["delivery_lowest_price"] = float(lowest.get("amount", 0))
        except (ValueError, TypeError):
            pass

    return result


# --- Glowna logika ---
print("=" * 80)
print("ANALIZA RYNKOWA ALLEGRO - AKCESORIA DLA PSOW")
print("=" * 80)

all_results = {}
total_offers = 0

for key, phrase in SEARCH_QUERIES.items():
    print(f"\n  Wyszukiwanie: '{phrase}'...", file=sys.stderr)
    offers = search_allegro_listing(phrase, max_pages=2)
    all_results[key] = offers
    total_offers += len(offers)
    print(f"    Znaleziono: {len(offers)} ofert", file=sys.stderr)
    time.sleep(0.5)  # Rate limiting miedzy zapytaniami

print(f"\nLaczne zebrano: {total_offers} ofert", file=sys.stderr)

# ============================================================
# ANALIZA 1: Produkty Truelove na Allegro
# ============================================================
print(f"\n{'='*80}")
print("1. PRODUKTY TRUELOVE DOSTEPNE NA ALLEGRO")
print(f"{'='*80}")

truelove_categories = {}
for key, offers in all_results.items():
    if not key.startswith("truelove_"):
        continue
    category_name = key.replace("truelove_", "").upper()

    if not offers:
        truelove_categories[category_name] = {"count": 0, "offers": []}
        print(f"\n  {category_name}: BRAK OFERT")
        continue

    prices = [o["price"] for o in offers if o.get("price")]
    sellers = set(o.get("seller_login", "") for o in offers if o.get("seller_login"))

    truelove_categories[category_name] = {
        "count": len(offers),
        "prices": prices,
        "sellers": sellers,
        "offers": offers,
    }

    if prices:
        print(f"\n  {category_name}: {len(offers)} ofert")
        print(f"    Ceny: {min(prices):.2f} - {max(prices):.2f} PLN (srednia: {sum(prices)/len(prices):.2f})")
        print(f"    Sprzedawcow: {len(sellers)}")
        # Top 5 najtanszych
        sorted_offers = sorted(offers, key=lambda x: x.get("price", 9999))
        print(f"    Top 5 najtanszych:")
        for i, o in enumerate(sorted_offers[:5], 1):
            print(f"      {i}. {o.get('price', '?'):.2f} PLN - {o.get('name', '')[:70]}")
            print(f"         Sprzedawca: {o.get('seller_login', '?')}")
    else:
        print(f"\n  {category_name}: {len(offers)} ofert (brak danych cenowych)")

# ============================================================
# ANALIZA 2: Porownanie z rynkiem ogolnym
# ============================================================
print(f"\n{'='*80}")
print("2. RYNEK OGOLNY - POROWNANIE KATEGORII")
print(f"{'='*80}")

market_categories = {
    "szelki_pies": "Szelki dla psa",
    "szelki_antyuciagowe": "Szelki antyuciagowe",
    "smycz_pies": "Smycz dla psa",
    "obroza_pies": "Obroza dla psa",
    "akcesoria_pies_spacer": "Akcesoria spacerowe",
    "peleryna_pies": "Peleryna przeciwdeszczowa",
    "kamizelka_pies": "Kamizelka odblaskowa",
}

for key, label in market_categories.items():
    offers = all_results.get(key, [])
    if not offers:
        print(f"\n  {label}: BRAK DANYCH")
        continue

    prices = [o["price"] for o in offers if o.get("price")]
    sellers = set(o.get("seller_login", "") for o in offers if o.get("seller_login"))
    super_sellers = [o for o in offers if o.get("seller_superSeller")]

    print(f"\n  {label}: {len(offers)} ofert")
    if prices:
        print(f"    Rozpitosc cen: {min(prices):.2f} - {max(prices):.2f} PLN")
        print(f"    Srednia cena: {sum(prices)/len(prices):.2f} PLN")
        # Mediana
        sorted_prices = sorted(prices)
        mid = len(sorted_prices) // 2
        median = sorted_prices[mid] if len(sorted_prices) % 2 else (sorted_prices[mid-1] + sorted_prices[mid]) / 2
        print(f"    Mediana ceny: {median:.2f} PLN")
    print(f"    Sprzedawcow: {len(sellers)}")
    print(f"    SuperSprzedawcow: {len(super_sellers)}")

# ============================================================
# ANALIZA 3: Identyfikacja produktow Truelove, ktorych NIE sprzedajemy
# ============================================================
print(f"\n{'='*80}")
print("3. PRODUKTY TRUELOVE - MOZLIWOSCI ROZSZERZENIA OFERTY")
print(f"{'='*80}")

# Kategorie z ofertami
promising = []
no_offers = []

for cat, data in truelove_categories.items():
    if data["count"] > 0:
        promising.append((cat, data["count"]))
    else:
        no_offers.append(cat)

print(f"\n  Kategorie z ofertami na Allegro (potencjal sprzedazowy):")
for cat, count in sorted(promising, key=lambda x: x[1], reverse=True):
    print(f"    - {cat}: {count} ofert (konkurencja istnieje, rynek zweryfikowany)")

if no_offers:
    print(f"\n  Kategorie BEZ ofert (maly rynek lub brak zainteresowania):")
    for cat in no_offers:
        print(f"    - {cat}")

# Analiza nazw produktow Truelove - jakie modele/typy sprzedaja sie
print(f"\n  Popularne slowa kluczowe w ofertach Truelove:")
all_truelove_names = []
for key, offers in all_results.items():
    if key.startswith("truelove_"):
        for o in offers:
            name = o.get("name", "").lower()
            all_truelove_names.append(name)

word_counter = Counter()
stop_words = {"dla", "psa", "psy", "truelove", "the", "and", "szelki", "i", "z", "na",
              "w", "do", "od", "xl", "xxl", "xs", "s", "m", "l", "-", "nr", "dog",
              "harness", "leash"}
for name in all_truelove_names:
    words = name.replace(",", " ").replace(".", " ").replace("/", " ").split()
    for word in words:
        word = word.strip().lower()
        if len(word) > 2 and word not in stop_words:
            word_counter[word] += 1

print(f"    Top 20 slow kluczowych:")
for word, count in word_counter.most_common(20):
    print(f"      '{word}': {count}x")

# ============================================================
# ANALIZA 4: Analiza cen - gdzie jest nasza pozycja
# ============================================================
print(f"\n{'='*80}")
print("4. ANALIZA CENOWA SZELEK")
print(f"{'='*80}")

szelki_all = all_results.get("szelki_pies", [])
szelki_truelove = all_results.get("truelove_szelki", [])

if szelki_all:
    prices_all = sorted([o["price"] for o in szelki_all if o.get("price")])
    prices_truelove = sorted([o["price"] for o in szelki_truelove if o.get("price")])

    if prices_all:
        # Rozklad cen rynkowych
        quartiles = [
            prices_all[int(len(prices_all) * 0.25)],
            prices_all[int(len(prices_all) * 0.50)],
            prices_all[int(len(prices_all) * 0.75)],
        ]
        print(f"\n  Rynek szelek ogolnie ({len(prices_all)} ofert):")
        print(f"    Q1 (25%): {quartiles[0]:.2f} PLN")
        print(f"    Mediana:  {quartiles[1]:.2f} PLN")
        print(f"    Q3 (75%): {quartiles[2]:.2f} PLN")
        print(f"    Min: {prices_all[0]:.2f}, Max: {prices_all[-1]:.2f} PLN")

        # Przedzialy cenowe
        ranges = [(0, 30), (30, 60), (60, 100), (100, 150), (150, 200), (200, 999)]
        print(f"\n    Dystrybucja cenowa:")
        for low, high in ranges:
            count = len([p for p in prices_all if low <= p < high])
            pct = count / len(prices_all) * 100 if prices_all else 0
            bar = "#" * int(pct / 2)
            label = f"{low}-{high}" if high < 999 else f"{low}+"
            print(f"      {label:>8} PLN: {count:>3} ({pct:>5.1f}%) {bar}")

    if prices_truelove:
        print(f"\n  Szelki Truelove ({len(prices_truelove)} ofert):")
        print(f"    Min: {prices_truelove[0]:.2f} PLN")
        print(f"    Max: {prices_truelove[-1]:.2f} PLN")
        avg = sum(prices_truelove) / len(prices_truelove)
        print(f"    Srednia: {avg:.2f} PLN")

# ============================================================
# ANALIZA 5: Top sprzedawcy
# ============================================================
print(f"\n{'='*80}")
print("5. TOP SPRZEDAWCY TRUELOVE NA ALLEGRO")
print(f"{'='*80}")

seller_counter = Counter()
seller_offers = defaultdict(list)

for key, offers in all_results.items():
    if key.startswith("truelove_"):
        for o in offers:
            seller = o.get("seller_login", "")
            if seller:
                seller_counter[seller] += 1
                seller_offers[seller].append(o)

print(f"\n  Top 15 sprzedawcow (wg liczby ofert Truelove):")
for seller, count in seller_counter.most_common(15):
    offers = seller_offers[seller]
    prices = [o["price"] for o in offers if o.get("price")]
    super_seller = any(o.get("seller_superSeller") for o in offers)
    badge = " [SuperSprzedawca]" if super_seller else ""
    avg_price = sum(prices) / len(prices) if prices else 0
    print(f"    {seller}{badge}: {count} ofert, srednia cena {avg_price:.2f} PLN")

# ============================================================
# ANALIZA 6: Rekomendacje
# ============================================================
print(f"\n{'='*80}")
print("6. REKOMENDACJE STRATEGICZNE")
print(f"{'='*80}")

print("""
  PRODUKTY TRUELOVE DO ROZSZERZENIA OFERTY:
  -----------------------------------------
  Na podstawie analizy ofert na Allegro, sprawdz nastepujace kategorie:
""")

for cat, data in sorted(truelove_categories.items(), key=lambda x: x[1]["count"], reverse=True):
    if data["count"] > 5:
        prices = data.get("prices", [])
        avg = sum(prices) / len(prices) if prices else 0
        print(f"    * {cat}: {data['count']} ofert, srednia {avg:.2f} PLN")
        print(f"      -> Rynek istnieje, warto rozwazyc dodanie do oferty")

print("""
  STRATEGIA CENOWA:
  -----------------
  - Pozycjonuj sie w segmencie premium (Truelove jest marka premium)
  - Utrzymuj ceny w gornych 50% rynku, ale ponizej najwyzszych
  - Wyrozniaj sie jako specjalista od Truelove (pelna oferta)

  STRATEGIE ALLEGRO:
  ------------------
  - Wyroznienia ofert (wzrost widocznosci o 30-50%)
  - Allegro Smart - darmowa dostawa przyciaga klientow
  - Oferuj zestawy (szelki + smycz) - wyzsze AOV
  - Optymalizuj tytuly i opisy pod wyszukiwarke Allegro
  - Zadbaj o ocene sprzedawcy - kluczowa dla konwersji
  - Rozważ program Allegro Ceny jesli pozwala na to marza

  SEZONOWOS'C:
  ------------
  - Wiosna/lato: szelki spacerowe, smycze, akcesoria na spacer
  - Jesien/zima: ubranko, kamizelka odblaskowa, peleryna
""")

# Zapisz surowe dane do pliku JSON
output = {
    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    "queries": dict(SEARCH_QUERIES),
    "results": {},
}
for key, offers in all_results.items():
    output["results"][key] = {
        "count": len(offers),
        "offers": offers,
    }

print(json.dumps(output, ensure_ascii=False, indent=2), file=sys.stderr)

print(f"\n{'='*80}")
print("KONIEC ANALIZY RYNKOWEJ")
print(f"{'='*80}")
