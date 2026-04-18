"""Test nowego parsowania: kategoria + seria."""
import sys
sys.path.insert(0, r"c:\Users\sucho\retrievershop-suite")

from magazyn.parsing import _detect_product_name, parse_offer_title

tests = [
    # (tytul, oczekiwana_nazwa, oczekiwany_kolor, oczekiwany_rozmiar)
    # Cordura
    ("Szelki guard dla duzego psa Truelove Front Line Premium Cordura XL czarne",
     "Szelki dla psa Truelove Front Line Premium Cordura", "Czarny", "XL"),
    ("Szelki guard dla duzego psa Truelove Front Line Cordura L pomaranczowe",
     "Szelki dla psa Truelove Front Line Premium Cordura", "Pomarańczowy", "L"),
    # Obroza vs Szelki Lumen
    ("Obroza dla psa materialowa odblaskowa Truelove Lumen M czarna",
     "Obroża dla psa Truelove Lumen", "Czarny", "M"),
    ("Obroza dla psa materialowa treningowa Truelove Lumen L czarna",
     "Obroża dla psa Truelove Lumen", "Czarny", "L"),
    ("Obroza dla psa materialowa odblaskowa Truelove Lumen L zolta",
     "Obroża dla psa Truelove Lumen", "", "L"),
    ("Obroza dla psa materialowa odblaskowa Truelove Active L czerwona",
     "Obroża dla psa Truelove Active", "Czerwony", "L"),
    # Obroza Tropical
    ("Obroza dla psa Truelove Tropical L",
     "Obroża dla psa Truelove Tropical", "", "L"),
    # Obroza Dogi
    ("Obroza dla psa materialowa Truelove Dogi L czarna",
     "Obroża dla psa Truelove Dogi", "Czarny", "L"),
    # Szelki normalne
    ("Szelki guard dla duzego psa Truelove Front Line Premium XL czarne",
     "Szelki dla psa Truelove Front Line Premium", "Czarny", "XL"),
    ("Szelki dla psa Truelove Lumen L czarne",
     "Szelki dla psa Truelove Lumen", "Czarny", "L"),
    ("Szelki antyucieczkowe dla duzego psa Truelove Adventure Soft L czarne",
     "Szelki dla psa Truelove Adventure Soft", "Czarny", "L"),
    # Smycz
    ("Smycz automatyczna Truelove Handy 5 metrow czarna",
     "Smycz dla psa Truelove Handy", "Czarny", "Uniwersalny"),
    ("Smycz dla psa z amortyzatorem Truelove Adventure 160cm czarna M",
     "Smycz dla psa Truelove Adventure", "Czarny", "M"),
    # Amortyzator
    ("Amortyzator do smyczy dla sredniego psa Truelove czarny",
     "Amortyzator dla psa Truelove Premium", "Czarny", "Uniwersalny"),
    # Pas
    ("Pas samochodowy dla psa Truelove Premium czarny",
     "Pas samochodowy dla psa Truelove Premium", "Czarny", "Uniwersalny"),
    ("Pas trekkingowy Truelove Trek Go pomaranczowy",
     "Pas trekkingowy dla psa Truelove Trek Go", "Pomarańczowy", "Uniwersalny"),
    # Szelki bez serii
    ("Szelki dla psa Truelove L zolte",
     "Szelki dla psa Truelove", "", "L"),
    # Saszetki
    ("Saszetka na przysmaki Truelove limonkowa",
     "Saszetki dla psa Truelove", "", "Uniwersalny"),
    ("Saszetka z rzepami do szelek Truelove V2 czarna",
     "Saszetki dla psa Truelove V2", "Czarny", "Uniwersalny"),
    ("Saszetka na ramie nerka Truelove Trail Bag czarna",
     "Saszetki dla psa Truelove Trail Bag", "Czarny", "Uniwersalny"),
    # Aliasy - Front Line Premium + seria -> ta seria wygrywa
    ("Szelki dla psa Truelove Front Line Premium Tropical L turkusowe",
     "Szelki dla psa Truelove Tropical", "Turkusowy", "L"),
    ("Szelki dla psa Truelove FrontLine Lumen S czerwone",
     "Szelki dla psa Truelove Lumen", "Czerwony", "S"),
    ("Szelki dla psa Truelove Front Line Premium Blossom XS rozowe",
     "Szelki dla psa Truelove Blossom", "", "XS"),
    # Literowki
    ("Szelki dla psa Truelove Fron Line Premium M czarne",
     "Szelki dla psa Truelove Front Line Premium", "Czarny", "M"),
    ("Szelki dla psa Truelobve Front-Line L czerwone",
     "Szelki dla psa Truelove Front Line", "Czerwony", "L"),
]

ok = 0
fail = 0
for title, exp_name, exp_color, exp_size in tests:
    name, color, size = parse_offer_title(title)
    if name != exp_name:
        fail += 1
        print(f"FAIL: \"{title[:55]}\"")
        print(f"  got:  name={name}")
        print(f"  want: name={exp_name}")
    else:
        ok += 1
        color_ok = exp_color == "" or color == exp_color
        size_ok = size == exp_size
        if not color_ok or not size_ok:
            print(f"WARN: \"{title[:55]}\" name OK, ale color={color}(want {exp_color}), size={size}(want {exp_size})")
        else:
            print(f"OK: \"{title[:55]}\" -> {name} | {color} | {size}")

print(f"\n{ok} OK, {fail} FAIL")
if fail:
    sys.exit(1)
