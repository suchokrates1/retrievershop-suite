"""
Kompleksowa analiza zamowien RetrieverShop
------------------------------------------
Analiza trendow, bestsellerow, zachowan klientow, metod dostawy,
czasow sprzedazy, cen i rekomendacji strategicznych.
"""
import json
import os
from datetime import datetime, timedelta
from collections import Counter, defaultdict

# Wczytaj dane
script_dir = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(script_dir, "orders_data.json"), encoding="utf-8") as f:
    orders = json.load(f)

print(f"=" * 80)
print(f"ANALIZA ZAMOWIEN RETRIEVERSHOP")
print(f"Laczna liczba zamowien: {len(orders)}")
print(f"=" * 80)

# ============================================================
# 1. PODSTAWOWE STATYSTYKI
# ============================================================
print(f"\n{'='*80}")
print("1. PODSTAWOWE STATYSTYKI")
print(f"{'='*80}")

total_revenue = 0
total_products = 0
order_values = []
dates = []

for o in orders:
    payment = o.get("payment_done", 0) or 0
    total_revenue += payment
    order_values.append(payment)
    
    date_add = o.get("date_add")
    if date_add:
        try:
            dt = datetime.fromtimestamp(int(date_add))
            dates.append(dt)
        except (ValueError, OSError):
            pass
    
    for p in o.get("products", []):
        total_products += p.get("quantity", 1) or 1

if dates:
    dates.sort()
    period_start = dates[0]
    period_end = dates[-1]
    period_days = (period_end - period_start).days or 1
    print(f"Okres: {period_start.strftime('%Y-%m-%d')} - {period_end.strftime('%Y-%m-%d')} ({period_days} dni)")
else:
    period_days = 1

print(f"Laczny przychod: {total_revenue:.2f} PLN")
print(f"Srednia wartosc zamowienia (AOV): {total_revenue / len(orders):.2f} PLN")
print(f"Mediana wartosci zamowienia: {sorted(order_values)[len(order_values)//2]:.2f} PLN")
print(f"Laczna ilosc produktow: {total_products}")
print(f"Srednia produktow na zamowienie: {total_products / len(orders):.1f}")
print(f"Zamowienia/dzien (srednia): {len(orders) / period_days:.2f}")
print(f"Przychod/dzien (srednia): {total_revenue / period_days:.2f} PLN")

# Rozklad wartosci zamowien
print(f"\nRozklad wartosci zamowien:")
brackets = [(0, 50), (50, 100), (100, 150), (150, 200), (200, 300), (300, 500), (500, 10000)]
for low, high in brackets:
    count = sum(1 for v in order_values if low <= v < high)
    pct = count / len(order_values) * 100
    bar = "#" * int(pct / 2)
    if high < 10000:
        print(f"  {low:>4}-{high:<4} PLN: {count:>3} ({pct:>5.1f}%) {bar}")
    else:
        print(f"  {low:>4}+    PLN: {count:>3} ({pct:>5.1f}%) {bar}")

# ============================================================
# 2. BESTSELLERY - NAJCZESCIEJ SPRZEDAWANE PRODUKTY
# ============================================================
print(f"\n{'='*80}")
print("2. BESTSELLERY - TOP 20 PRODUKTOW")
print(f"{'='*80}")

product_sales = Counter()
product_revenue = defaultdict(float)
product_prices = defaultdict(list)

for o in orders:
    for p in o.get("products", []):
        name = p.get("name", "Nieznany")
        qty = p.get("quantity", 1) or 1
        price = p.get("price_brutto", 0) or 0
        product_sales[name] += qty
        product_revenue[name] += price * qty
        product_prices[name].append(price)

print("\nTop 20 wg ilosci sprzedanych:")
for i, (name, qty) in enumerate(product_sales.most_common(20), 1):
    rev = product_revenue[name]
    avg_price = sum(product_prices[name]) / len(product_prices[name])
    print(f"  {i:>2}. [{qty:>3}x] {name[:65]}")
    print(f"      Przychod: {rev:.2f} PLN | Srednia cena: {avg_price:.2f} PLN")

print("\nTop 10 wg przychodu:")
for i, (name, rev) in enumerate(sorted(product_revenue.items(), key=lambda x: -x[1])[:10], 1):
    qty = product_sales[name]
    print(f"  {i:>2}. [{rev:>8.2f} PLN] {name[:55]} ({qty}x)")

# ============================================================
# 3. ANALIZA KATEGORII PRODUKTOW
# ============================================================
print(f"\n{'='*80}")
print("3. ANALIZA KATEGORII PRODUKTOW")
print(f"{'='*80}")

# Kategoryzacja po slowach kluczowych
categories = {
    "Szelki": ["szelki", "harness"],
    "Smycze": ["smycz", "leash"],
    "Amortyzatory": ["amortyzator", "bungee"],
    "Obroze": ["obroz", "collar"],
    "Inne": [],
}

cat_stats = defaultdict(lambda: {"qty": 0, "revenue": 0.0, "orders": set()})

for o in orders:
    for p in o.get("products", []):
        name = (p.get("name") or "").lower()
        qty = p.get("quantity", 1) or 1
        price = p.get("price_brutto", 0) or 0
        
        matched = False
        for cat, keywords in categories.items():
            if cat == "Inne":
                continue
            if any(kw in name for kw in keywords):
                cat_stats[cat]["qty"] += qty
                cat_stats[cat]["revenue"] += price * qty
                cat_stats[cat]["orders"].add(o["order_id"])
                matched = True
                break
        if not matched:
            cat_stats["Inne"]["qty"] += qty
            cat_stats["Inne"]["revenue"] += price * qty
            cat_stats["Inne"]["orders"].add(o["order_id"])

print(f"\n{'Kategoria':<20} {'Ilosc':>8} {'Przychod':>12} {'Zamowien':>10} {'Udz.przychodowy':>16}")
print("-" * 70)
total_cat_rev = sum(c["revenue"] for c in cat_stats.values())
for cat in sorted(cat_stats.keys(), key=lambda c: -cat_stats[c]["revenue"]):
    s = cat_stats[cat]
    pct = s["revenue"] / total_cat_rev * 100 if total_cat_rev else 0
    print(f"  {cat:<18} {s['qty']:>8} {s['revenue']:>10.2f} PLN {len(s['orders']):>8} {pct:>14.1f}%")

# ============================================================
# 4. ANALIZA CZASOWA - TRENDY
# ============================================================
print(f"\n{'='*80}")
print("4. ANALIZA CZASOWA - TRENDY SPRZEDAZY")
print(f"{'='*80}")

# Zamowienia wg miesiaca
monthly = defaultdict(lambda: {"count": 0, "revenue": 0.0})
weekly = defaultdict(lambda: {"count": 0, "revenue": 0.0})
hourly = defaultdict(int)
daily_dow = defaultdict(lambda: {"count": 0, "revenue": 0.0})

DOW_NAMES = ["Poniedzialek", "Wtorek", "Sroda", "Czwartek", "Piatek", "Sobota", "Niedziela"]

for o in orders:
    date_add = o.get("date_add")
    payment = o.get("payment_done", 0) or 0
    if date_add:
        try:
            dt = datetime.fromtimestamp(int(date_add))
            month_key = dt.strftime("%Y-%m")
            monthly[month_key]["count"] += 1
            monthly[month_key]["revenue"] += payment
            
            week_key = dt.strftime("%Y-W%V")
            weekly[week_key]["count"] += 1
            weekly[week_key]["revenue"] += payment
            
            hourly[dt.hour] += 1
            
            dow = dt.weekday()
            daily_dow[dow]["count"] += 1
            daily_dow[dow]["revenue"] += payment
        except (ValueError, OSError):
            pass

print("\nZamowienia wg miesiaca:")
for month in sorted(monthly.keys()):
    s = monthly[month]
    bar = "#" * (s["count"] * 2)
    print(f"  {month}: {s['count']:>3} zamowien | {s['revenue']:>8.2f} PLN | {bar}")

print(f"\nTrend: ", end="")
months_sorted = sorted(monthly.keys())
if len(months_sorted) >= 2:
    first_half = months_sorted[:len(months_sorted)//2]
    second_half = months_sorted[len(months_sorted)//2:]
    avg_first = sum(monthly[m]["revenue"] for m in first_half) / len(first_half)
    avg_second = sum(monthly[m]["revenue"] for m in second_half) / len(second_half)
    if avg_second > avg_first * 1.1:
        print(f"ROSNACY (+{((avg_second/avg_first)-1)*100:.0f}%)")
    elif avg_second < avg_first * 0.9:
        print(f"MALEJACY ({((avg_second/avg_first)-1)*100:.0f}%)")
    else:
        print("STABILNY")

print("\nZamowienia wg dnia tygodnia:")
for dow in range(7):
    if dow in daily_dow:
        s = daily_dow[dow]
        bar = "#" * (s["count"] * 2)
        print(f"  {DOW_NAMES[dow]:<14}: {s['count']:>3} zamowien | {s['revenue']:>8.2f} PLN | {bar}")

print("\nZamowienia wg godziny (UTC):")
for hour in range(24):
    if hourly[hour] > 0:
        bar = "#" * (hourly[hour] * 2)
        print(f"  {hour:>2}:00 - {hour:>2}:59: {hourly[hour]:>3} zamowien | {bar}")

# Najlepsza godzina/dzien
if hourly:
    best_hour = max(hourly, key=hourly.get)
    print(f"\n  Najlepsza godzina: {best_hour}:00 ({hourly[best_hour]} zamowien)")
if daily_dow:
    best_dow = max(daily_dow, key=lambda d: daily_dow[d]["count"])
    print(f"  Najlepszy dzien: {DOW_NAMES[best_dow]} ({daily_dow[best_dow]['count']} zamowien)")

# ============================================================
# 5. ANALIZA KLIENTOW
# ============================================================
print(f"\n{'='*80}")
print("5. ANALIZA KLIENTOW")
print(f"{'='*80}")

customer_orders = defaultdict(lambda: {"count": 0, "revenue": 0.0, "products": []})
for o in orders:
    key = o.get("email") or o.get("user_login") or o.get("customer_name") or "unknown"
    payment = o.get("payment_done", 0) or 0
    customer_orders[key]["count"] += 1
    customer_orders[key]["revenue"] += payment
    for p in o.get("products", []):
        customer_orders[key]["products"].append(p.get("name", ""))

total_customers = len(customer_orders)
repeat_customers = sum(1 for c in customer_orders.values() if c["count"] > 1)
single_customers = total_customers - repeat_customers

print(f"Laczna liczba unikalnych klientow: {total_customers}")
print(f"Klienci jednorazowi: {single_customers} ({single_customers/total_customers*100:.1f}%)")
print(f"Klienci powracajacy (2+ zamowien): {repeat_customers} ({repeat_customers/total_customers*100:.1f}%)")

if repeat_customers:
    repeat_revenue = sum(c["revenue"] for c in customer_orders.values() if c["count"] > 1)
    single_revenue = sum(c["revenue"] for c in customer_orders.values() if c["count"] == 1)
    print(f"\nPrzychod od klientow powracajacych: {repeat_revenue:.2f} PLN ({repeat_revenue/total_revenue*100:.1f}%)")
    print(f"Przychod od klientow jednorazowych: {single_revenue:.2f} PLN ({single_revenue/total_revenue*100:.1f}%)")
    
    print(f"\nTop powracajacy klienci:")
    for i, (key, data) in enumerate(sorted(customer_orders.items(), key=lambda x: -x[1]["count"])[:10], 1):
        if data["count"] > 1:
            print(f"  {i}. {key[:40]} - {data['count']} zamowien, {data['revenue']:.2f} PLN")

# Klienci biznesowi (z NIP)
biz_orders = [o for o in orders if o.get("invoice_nip") or o.get("invoice_company")]
print(f"\nZamowienia firmowe (z NIP/firma): {len(biz_orders)} ({len(biz_orders)/len(orders)*100:.1f}%)")

# ============================================================
# 6. ANALIZA DOSTAW
# ============================================================
print(f"\n{'='*80}")
print("6. ANALIZA METOD DOSTAWY")
print(f"{'='*80}")

delivery_methods = Counter()
delivery_prices = defaultdict(list)
courier_stats = Counter()

for o in orders:
    method = o.get("delivery_method") or "Nieznana"
    delivery_methods[method] += 1
    price = o.get("delivery_price", 0) or 0
    delivery_prices[method].append(price)
    
    courier = o.get("delivery_package_module") or "brak"
    courier_stats[courier] += 1

print("\nMetody dostawy:")
for method, count in delivery_methods.most_common():
    pct = count / len(orders) * 100
    avg_price = sum(delivery_prices[method]) / len(delivery_prices[method])
    bar = "#" * int(pct / 2)
    print(f"  {method[:50]:<50} {count:>3} ({pct:>5.1f}%) sr.cena: {avg_price:.2f} PLN {bar}")

print("\nKurierzy:")
for courier, count in courier_stats.most_common():
    pct = count / len(orders) * 100
    print(f"  {courier:<30} {count:>3} ({pct:>5.1f}%)")

# Paczkomat vs kurier
paczkomat = sum(1 for o in orders if o.get("delivery_point_name"))
kurier = len(orders) - paczkomat
print(f"\nPaczkomat/punkt odbioru: {paczkomat} ({paczkomat/len(orders)*100:.1f}%)")
print(f"Kurier do domu: {kurier} ({kurier/len(orders)*100:.1f}%)")

# ============================================================
# 7. ANALIZA GEOGRAFICZNA
# ============================================================
print(f"\n{'='*80}")
print("7. ANALIZA GEOGRAFICZNA")
print(f"{'='*80}")

cities = Counter()
regions = Counter()  # wg kodu pocztowego (pierwsze 2 cyfry)

REGION_MAP = {
    "00": "Warszawa", "01": "Warszawa", "02": "Warszawa", "03": "Warszawa", "04": "Warszawa", "05": "Okolice Warszawy",
    "06": "Płock/Ostrołęka", "07": "Ostrołęka/Siedlce", "08": "Siedlce/Radom", "09": "Płock",
    "10": "Olsztyn", "11": "Olsztyn", "12": "Ełk/Suwałki", "13": "Elbląg", "14": "Olsztyn",
    "15": "Białystok", "16": "Białystok", "17": "Zamość", "18": "Białystok", "19": "Białystok",
    "20": "Lublin", "21": "Lublin", "22": "Zamość", "23": "Zamość", "24": "Radom",
    "25": "Kielce", "26": "Radom", "27": "Kielce", "28": "Kielce", "29": "Kielce",
    "30": "Kraków", "31": "Kraków", "32": "Kraków", "33": "Tarnów", "34": "Nowy Sącz",
    "35": "Rzeszów", "36": "Rzeszów", "37": "Rzeszów", "38": "Rzeszów", "39": "Tarnobrzeg",
    "40": "Katowice", "41": "Katowice", "42": "Częstochowa", "43": "Bielsko-Biała", "44": "Katowice",
    "45": "Opole", "46": "Opole", "47": "Opole", "48": "Opole", "49": "Opole",
    "50": "Wrocław", "51": "Wrocław", "52": "Wrocław", "53": "Wrocław", "54": "Wrocław",
    "55": "Wrocław", "56": "Legnica", "57": "Wałbrzych", "58": "Jelenia Góra", "59": "Legnica",
    "60": "Poznań", "61": "Poznań", "62": "Kalisz", "63": "Leszno", "64": "Piła",
    "65": "Zielona Góra", "66": "Gorzów", "67": "Zielona Góra", "68": "Zielona Góra", "69": "Zielona Góra",
    "70": "Szczecin", "71": "Szczecin", "72": "Koszalin", "73": "Szczecin", "74": "Koszalin",
    "75": "Koszalin", "76": "Słupsk", "77": "Koszalin", "78": "Szczecin",
    "80": "Gdańsk", "81": "Gdynia", "82": "Elbląg", "83": "Gdańsk", "84": "Gdańsk",
    "85": "Bydgoszcz", "86": "Bydgoszcz", "87": "Toruń", "88": "Bydgoszcz", "89": "Bydgoszcz",
    "90": "Łódź", "91": "Łódź", "92": "Łódź", "93": "Łódź", "94": "Łódź",
    "95": "Łódź", "96": "Łódź", "97": "Piotrków Tryb.", "98": "Sieradz", "99": "Łódź",
}

for o in orders:
    city = o.get("delivery_city") or "Nieznane"
    cities[city] += 1
    
    postcode = o.get("delivery_postcode") or ""
    prefix = postcode[:2].replace("-", "")
    if prefix in REGION_MAP:
        regions[REGION_MAP[prefix]] += 1
    else:
        regions["Inne/Zagraniczne"] += 1

print("\nTop 15 miast:")
for city, count in cities.most_common(15):
    pct = count / len(orders) * 100
    bar = "#" * int(pct)
    print(f"  {city:<25} {count:>3} ({pct:>5.1f}%) {bar}")

print("\nTop 10 regionow:")
for region, count in regions.most_common(10):
    pct = count / len(orders) * 100
    bar = "#" * int(pct)
    print(f"  {region:<25} {count:>3} ({pct:>5.1f}%) {bar}")

# ============================================================
# 8. ANALIZA CEN
# ============================================================
print(f"\n{'='*80}")
print("8. ANALIZA CEN PRODUKTOW")
print(f"{'='*80}")

all_prices = []
for name, prices in product_prices.items():
    for p in prices:
        if p > 0:
            all_prices.append(p)

if all_prices:
    all_prices.sort()
    print(f"Najnizsza cena produktu: {min(all_prices):.2f} PLN")
    print(f"Najwyzsza cena produktu: {max(all_prices):.2f} PLN")
    print(f"Srednia cena produktu: {sum(all_prices) / len(all_prices):.2f} PLN")
    print(f"Mediana ceny: {all_prices[len(all_prices)//2]:.2f} PLN")

    print("\nRozklad cen produktow:")
    price_brackets = [(0, 30), (30, 50), (50, 80), (80, 100), (100, 150), (150, 200), (200, 500)]
    for low, high in price_brackets:
        count = sum(1 for p in all_prices if low <= p < high)
        pct = count / len(all_prices) * 100
        bar = "#" * int(pct / 2)
        if high < 500:
            print(f"  {low:>4}-{high:<4} PLN: {count:>3} ({pct:>5.1f}%) {bar}")
        else:
            print(f"  {low:>4}+    PLN: {count:>3} ({pct:>5.1f}%) {bar}")

# Analiza rozmiarow
print("\nPopularne rozmiary (z nazw produktow):")
size_counter = Counter()
for name in product_sales:
    name_upper = name.upper()
    for size in ["XXS", "XS", "S", "M", "L", "XL", "XXL", "XXXL"]:
        if f" {size} " in f" {name_upper} " or name_upper.endswith(f" {size}"):
            size_counter[size] += product_sales[name]
            break

for size, count in size_counter.most_common():
    pct = count / sum(size_counter.values()) * 100
    bar = "#" * int(pct / 2)
    print(f"  {size:<5}: {count:>3} ({pct:>5.1f}%) {bar}")

# Analiza kolorow
print("\nPopularne kolory:")
color_counter = Counter()
colors_list = ["czarn", "biał", "czerwon", "niebieski", "zielon", "brązow", "szar", 
               "różow", "fioletow", "pomarańczow", "turkusow", "granatow"]
color_names = {"czarn": "Czarny", "biał": "Biały", "czerwon": "Czerwony", "niebieski": "Niebieski",
               "zielon": "Zielony", "brązow": "Brązowy", "szar": "Szary", "różow": "Różowy",
               "fioletow": "Fioletowy", "pomarańczow": "Pomarańczowy", "turkusow": "Turkusowy",
               "granatow": "Granatowy"}

for name, qty in product_sales.items():
    name_lower = name.lower()
    for color_key in colors_list:
        if color_key in name_lower:
            color_counter[color_names[color_key]] += qty
            break

for color, count in color_counter.most_common():
    pct = count / sum(color_counter.values()) * 100
    bar = "#" * int(pct / 2)
    print(f"  {color:<15}: {count:>3} ({pct:>5.1f}%) {bar}")

# ============================================================
# 9. ANALIZA PLATNOSCI
# ============================================================
print(f"\n{'='*80}")
print("9. ANALIZA PLATNOSCI")
print(f"{'='*80}")

payment_methods = Counter()
for o in orders:
    pm = o.get("payment_method") or "Nieznana"
    payment_methods[pm] += 1

for pm, count in payment_methods.most_common():
    pct = count / len(orders) * 100
    print(f"  {pm[:50]:<50} {count:>3} ({pct:>5.1f}%)")

# Zamowienia z faktura
invoice_count = sum(1 for o in orders if o.get("want_invoice"))
print(f"\nZamowienia z faktura: {invoice_count} ({invoice_count/len(orders)*100:.1f}%)")

# ============================================================
# 10. REKOMENDACJE STRATEGICZNE
# ============================================================
print(f"\n{'='*80}")
print("10. REKOMENDACJE I STRATEGIA")
print(f"{'='*80}")

recommendations = []

# 1. AOV
aov = total_revenue / len(orders)
if aov < 100:
    recommendations.append(
        f"NISKI AOV ({aov:.0f} PLN): Rozważ bundling produktow (szelki + smycz), "
        f"darmowa dostawa od wyzszej kwoty, upselling akcesoriow."
    )
elif aov > 150:
    recommendations.append(
        f"SOLIDNY AOV ({aov:.0f} PLN): Klienci kupuja wartosc. Mozna testowac premium linie produktow."
    )

# 2. Repeat rate
if total_customers > 0:
    repeat_rate = repeat_customers / total_customers * 100
    if repeat_rate < 15:
        recommendations.append(
            f"NISKI WSKAZNIK POWROTOW ({repeat_rate:.1f}%): Wdróż program lojalnosciowy, "
            f"email marketing z rabatami na kolejne zakupy, personalizowane rekomendacje."
        )
    elif repeat_rate > 25:
        recommendations.append(
            f"DOBRY WSKAZNIK POWROTOW ({repeat_rate:.1f}%): Klienci wracają. "
            f"Wzmocnij program referencyjny (polecam znajomemu)."
        )

# 3. Bestsellery
top_product = product_sales.most_common(1)[0] if product_sales else None
if top_product:
    top_pct = top_product[1] / total_products * 100
    if top_pct > 20:
        recommendations.append(
            f"KONCENTRACJA NA JEDNYM PRODUKCIE ({top_product[0][:40]}, {top_pct:.0f}% sprzedazy): "
            f"Ryzyko zaleznosci. Dywersyfikuj oferte, promuj inne produkty."
        )

# 4. Sezonowość
if monthly:
    months_data = sorted(monthly.items())
    if len(months_data) >= 3:
        recent = months_data[-1][1]["revenue"]
        prev = months_data[-2][1]["revenue"] if len(months_data) > 1 else recent
        if recent < prev * 0.7:
            recommendations.append(
                f"SPADEK SPRZEDAZY: Ostatni miesiac ({recent:.0f} PLN) nizszy o "
                f"{((1 - recent/prev) * 100):.0f}% od poprzedniego ({prev:.0f} PLN). "
                f"Rozważ promocje, nowy marketing."
            )
        elif recent > prev * 1.3:
            recommendations.append(
                f"WZROST SPRZEDAZY: Ostatni miesiac ({recent:.0f} PLN) wyzszy o "
                f"{((recent/prev - 1) * 100):.0f}% od poprzedniego. Utrzymuj momentum!"
            )

# 5. Dostawa
if paczkomat > kurier:
    recommendations.append(
        f"PACZKOMATY DOMINUJA ({paczkomat}/{len(orders)}): Upewnij się, "
        f"że masz najlepsze stawki InPost. Rozważ integrację Allegro Smart."
    )

# 6. Godziny
if hourly:
    best_hour = max(hourly, key=hourly.get)
    recommendations.append(
        f"SZCZYT SPRZEDAZY: godzina {best_hour}:00. Planuj promocje, "
        f"wyrozniania i reklamy na te godziny."
    )

# 7. Rozmiary
if size_counter:
    top_size = size_counter.most_common(1)[0]
    recommendations.append(
        f"NAJPOPULARNIEJSZY ROZMIAR: {top_size[0]} ({top_size[1]} szt). "
        f"Upewnij się, że zawsze masz ten rozmiar na stanie."
    )

# 8. Kolory
if color_counter:
    top_color = color_counter.most_common(1)[0]
    recommendations.append(
        f"NAJPOPULARNIEJSZY KOLOR: {top_color[0]} ({top_color[1]} szt). "
        f"Priorytetowo zaopatruj sie w ten kolor."
    )

# 9. Produkty z niskim matchingiem (NOT MATCHED)
unmatched = sum(1 for o in orders for p in o.get("products", []) if not p.get("product_size_id"))
if unmatched > total_products * 0.3:
    recommendations.append(
        f"PROBLEM Z MATCHINGIEM PRODUKTOW: {unmatched}/{total_products} produktow nie "
        f"dopasowanych do magazynu. Popraw nazwy/EAN w BaseLinker lub dodaj brakujące produkty."
    )

# 10. Darmowa dostawa
free_delivery = sum(1 for o in orders if (o.get("delivery_price") or 0) == 0)
if free_delivery > 0:
    recommendations.append(
        f"DARMOWA DOSTAWA: {free_delivery} zamowien ({free_delivery/len(orders)*100:.1f}%) "
        f"z darmowa dostawa. Jesli to za dużo, podnieś próg darmowej dostawy."
    )

print()
for i, rec in enumerate(recommendations, 1):
    print(f"  {i}. {rec}")
    print()

# ============================================================
# PODSUMOWANIE
# ============================================================
print(f"\n{'='*80}")
print("PODSUMOWANIE")
print(f"{'='*80}")
print(f"""
Zamowien: {len(orders)}
Klientow: {total_customers}
Przychod: {total_revenue:.2f} PLN  
AOV: {aov:.2f} PLN
Bestseller: {top_product[0][:50] if top_product else 'N/A'} ({top_product[1] if top_product else 0}x)
Wskaznik powrotow: {repeat_rate:.1f}% ({repeat_customers} klientow)
Najlepszy dzien: {DOW_NAMES[best_dow] if daily_dow else 'N/A'}
Najlepsza godzina: {best_hour if hourly else 'N/A'}:00
""")
