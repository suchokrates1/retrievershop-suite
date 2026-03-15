#!/usr/bin/env python3
"""
Skrypt do zmiany tytulow szelek na Allegro.

Dodaje "guard" i deskryptor rozmiaru do tytulow wszystkich szelek
POZA seria Active i Antyucieczkowe.

Format docelowy:
  Szelki guard dla duzego psa Truelove Lumen L czarne

Uzycie:
  python scripts/rename_szelki_guard.py          # dry-run (podglad zmian)
  python scripts/rename_szelki_guard.py --apply   # wykonaj zmiany
"""
import sys
import os
import re
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from magazyn.allegro_api.offers import change_offer_name, get_offer_details, fetch_offers
from magazyn.settings_store import settings_store

SIZE_DESC = {
    "XXL": "dla dużego psa",
    "XL": "dla dużego psa",
    "L": "dla dużego psa",
    "M": "dla średniego psa",
    "S": "dla małego psa",
    "XS": "dla małego psa",
}

# Serie do wykluczenia (bez zmian)
EXCLUDED_SERIES = ["active", "antyucieczkowe"]


def is_excluded(title):
    t = title.lower()
    return any(s in t for s in EXCLUDED_SERIES)


def normalize_title(title):
    """Popraw znane literowki w tytule przed dalszym przetwarzaniem."""
    t = title
    t = re.sub(r'XLczarne', 'XL czarne', t)
    t = re.sub(r'XLCzarne', 'XL Czarne', t, flags=re.IGNORECASE)
    return t


def extract_size(title):
    """Wyciagnij rozmiar z tytulu oferty."""
    t = normalize_title(title)
    # Najpierw wieloznakowe (kolejnosc: najdluzsze pierwsze)
    for s in ["XXL", "XL", "XS"]:
        if re.search(rf'\b{s}\b', t, re.IGNORECASE):
            return s.upper()
    # Jednoznakowe - tylko uppercase, nie wewnatrz slow
    for s in ["L", "M", "S"]:
        if re.search(rf'(?<![a-zA-Z]){s}(?![a-zA-Z])', t):
            return s
    return None


def build_new_title(current_title):
    """Zbuduj nowy tytul z 'guard' i deskryptorem rozmiaru."""
    t = current_title.strip()

    # Normalizuj wielkosc pierwszej litery
    if t and t[0].islower():
        t = t[0].upper() + t[1:]

    size = extract_size(t)
    if not size:
        return None, "Nie znaleziono rozmiaru"

    desc = SIZE_DESC[size]

    # Usun stary prefix
    rest = t

    # "Szelki dla psow olbrzymich XXL Truelove Outdoor"
    rest = re.sub(r'^Szelki\s+dla\s+psów\s+olbrzymich\s+XXL\s+', '', rest)
    # "Szelki dla psaTruelove..." (brak spacji)
    rest = re.sub(r'^Szelki\s+dla\s+psa(?=Truelove)', '', rest, flags=re.IGNORECASE)
    # "Szelki dla psa z lampka LED..."
    # "Szelki dla psa Truelove..."
    rest = re.sub(r'^Szelki\s+dla\s+psa\s+', '', rest, flags=re.IGNORECASE)
    # "Szelki Truelove..." (bez "dla psa")
    rest = re.sub(r'^Szelki\s+', '', rest, flags=re.IGNORECASE)

    rest = rest.strip()

    # Napraw literowki
    rest = rest.replace("Truellove", "Truelove")
    rest = rest.replace("TrueLove", "Truelove")
    rest = rest.replace("Ftont", "Front")
    rest = re.sub(r'XLczarne', 'XL czarne', rest)
    rest = re.sub(r'czerwono$', 'czerwone', rest)

    # Normalizuj wielkosc liter kolorow na koncu (np. "Czarne" -> "czarne")
    # Kolory: czarne, biale, czerwone, niebieskie, zielone, fioletowe, rozowe,
    # brazowe, granatowe, pomaranczowe, turkusowe, zolte, limonkowe, szare
    color_pattern = (
        r'\b(Czarne|Czarny|Czerwone|Turkusowe|Fioletowe|Niebieskie|Brazowe'
        r'|Brązowe|Granatowe|Pomarańczowe|Różowe|Żółte|Zielone|Limonkowe'
        r'|Szare|Białe)$'
    )
    rest = re.sub(color_pattern, lambda m: m.group(0).lower(), rest)

    # Dodaj rozmiar XXL jesli zostal usuniety z prefiksu "olbrzymich XXL"
    if size == "XXL" and not re.search(r'\bXXL\b', rest):
        rest = rest.rstrip() + " XXL"

    # Normalizuj "Xl" -> XL w tresci
    rest = re.sub(r'\bXl\b', 'XL', rest)

    new_title = f"Szelki guard {desc} {rest}"

    # Usun podwojne spacje
    new_title = re.sub(r'\s+', ' ', new_title).strip()

    return new_title, None


def fetch_all_szelki():
    """Pobierz wszystkie aktywne oferty szelek."""
    token = settings_store.get("ALLEGRO_ACCESS_TOKEN")
    if not token:
        print("BLAD: Brak tokenu Allegro!")
        sys.exit(1)

    all_offers = []
    offset = 0
    limit = 100

    while True:
        data = fetch_offers(token, offset=offset, limit=limit)
        offers = data.get("offers", [])
        if not offers:
            break
        for offer in offers:
            title = offer.get("name", "")
            offer_id = offer.get("id", "")
            pub = offer.get("publication", {}).get("status", "")
            if "szelki" in title.lower() and pub == "ACTIVE":
                all_offers.append({"id": offer_id, "title": title})
        total = data.get("totalCount", 0)
        offset += limit
        if offset >= total:
            break

    return all_offers


def main():
    apply = "--apply" in sys.argv

    print("=" * 70)
    print("Zmiana tytulow szelek na Allegro - dodanie 'guard' + rozmiar")
    print(f"Tryb: {'WYKONANIE ZMIAN' if apply else 'PODGLAD (dry-run)'}")
    print("=" * 70)

    offers = fetch_all_szelki()
    print(f"\nZnaleziono {len(offers)} aktywnych ofert szelek.\n")

    changes = []
    skipped = []
    errors = []

    for offer in sorted(offers, key=lambda o: o["title"]):
        oid = offer["id"]
        title = offer["title"]

        if is_excluded(title):
            skipped.append((oid, title, "seria wykluczona"))
            continue

        new_title, error = build_new_title(title)
        if error:
            errors.append((oid, title, error))
            continue

        if new_title == title:
            skipped.append((oid, title, "tytul juz poprawny"))
            continue

        # Sprawdz czy tytul juz ma "guard"
        if "guard" in title.lower():
            skipped.append((oid, title, "juz ma guard"))
            continue

        changes.append((oid, title, new_title))

    # Wyswietl planowane zmiany
    print(f"--- ZMIANY ({len(changes)}) ---")
    for oid, old, new in changes:
        print(f"  {oid}:")
        print(f"    STARY: {old}")
        print(f"    NOWY:  {new}")
        ln = len(new)
        if ln > 75:
            print(f"    UWAGA: {ln} znakow (moze przekroczyc limit Allegro)")
        print()

    if skipped:
        print(f"--- POMINIETE ({len(skipped)}) ---")
        for oid, title, reason in skipped:
            print(f"  {oid}: {title} [{reason}]")
        print()

    if errors:
        print(f"--- BLEDY ({len(errors)}) ---")
        for oid, title, error in errors:
            print(f"  {oid}: {title} [{error}]")
        print()

    # Wykonaj zmiany jesli --apply
    if apply and changes:
        print(f"Wykonuje {len(changes)} zmian...\n")
        success = 0
        fail = 0
        for i, (oid, old, new) in enumerate(changes, 1):
            print(f"[{i}/{len(changes)}] {oid}: {old[:50]}...")
            result = change_offer_name(oid, new)
            if result.get("success"):
                print(f"  OK -> {new}")
                success += 1
            else:
                print(f"  BLAD: {result.get('error')}")
                if result.get("details"):
                    print(f"  Szczegoly: {result.get('details')}")
                fail += 1
            # Rate limiting - 1s miedzy requestami
            if i < len(changes):
                time.sleep(1)

        print(f"\nPodsumowanie: {success} sukcesow, {fail} bledow")
        return 0 if fail == 0 else 1
    elif apply and not changes:
        print("Brak zmian do wykonania.")
    else:
        print(f"Aby wykonac zmiany, uruchom z flagą --apply")

    return 0


if __name__ == "__main__":
    sys.exit(main())
