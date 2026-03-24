"""
Dodatkowa ekstrakcja danych z pliku operacji finansowych Allegro
i poglębiona analiza statystyk ofert z reklam
"""
import pandas as pd
import re

# ============================================================================
# OPERACJE FINANSOWE - poprawne parsowanie kwot
# ============================================================================
print("=" * 80)
print("  OPERACJE FINANSOWE - SZCZEGOLOWA ANALIZA")
print("=" * 80)

OPERATIONS_XLSX = r"c:\Users\sucho\Downloads\2026-02-13_2026-03-16_872352211_operations_all.xlsx"

ops = pd.read_excel(OPERATIONS_XLSX)

def parse_kwota(val):
    """Parsuje kwoty w formacie '-217.00 zł' na float"""
    if pd.isna(val):
        return 0.0
    s = str(val).replace('\xa0', ' ').replace('zł', '').replace(' ', '').replace(',', '.')
    try:
        return float(s)
    except:
        return 0.0

ops['kwota_num'] = ops['kwota'].apply(parse_kwota)
ops['saldo_num'] = ops['saldo'].apply(parse_kwota)

# Parsuj daty
ops['data_parsed'] = pd.to_datetime(ops['data'], format='%d.%m.%Y %H:%M', errors='coerce')
ops['miesiac'] = ops['data_parsed'].dt.to_period('M')

print("\n### ROZBICIE OPERACJI WG TYPU ###\n")
by_type = ops.groupby('operacja').agg(
    liczba=('kwota_num', 'count'),
    suma=('kwota_num', 'sum'),
).sort_values('suma', ascending=True)

print(f"{'Typ operacji':<50} {'Liczba':<10} {'Suma PLN':<15}")
print("-" * 75)
for idx, row in by_type.iterrows():
    print(f"{idx:<50} {row['liczba']:<10} {row['suma']:>12,.2f}")

print(f"\n{'SALDO NETTO':<50} {'':10} {ops['kwota_num'].sum():>12,.2f}")

# ============================================================================
# Rozdziel na luty i marzec
# ============================================================================
print("\n\n### OPERACJE MIESIECZNE ###\n")

for period, group in ops.groupby('miesiac'):
    print(f"\n--- {period} ---")
    by_type_m = group.groupby('operacja').agg(
        liczba=('kwota_num', 'count'),
        suma=('kwota_num', 'sum'),
    ).sort_values('suma', ascending=True)
    
    print(f"{'Typ operacji':<50} {'Liczba':<10} {'Suma PLN':<15}")
    print("-" * 75)
    for idx, row in by_type_m.iterrows():
        print(f"{idx:<50} {row['liczba']:<10} {row['suma']:>12,.2f}")
    print(f"{'NETTO':50} {'':10} {group['kwota_num'].sum():>12,.2f}")

# ============================================================================
# Wplaty (sprzedaz) - szczegoly
# ============================================================================
print("\n\n### WPLATY (SPRZEDAZ) - MARZEC ###\n")

wplaty_mar = ops[(ops['operacja'] == 'wpłata') & (ops['data_parsed'] >= '2026-03-01')]
print(f"Liczba wpłat: {len(wplaty_mar)}")
print(f"Suma wpłat: {wplaty_mar['kwota_num'].sum():,.2f} PLN")

print(f"\n{'Data':<20} {'Kupujacy':<40} {'Oferta':<50} {'Kwota':<12}")
print("-" * 122)
for _, row in wplaty_mar.iterrows():
    buyer = str(row.get('kupujący', ''))[:38] if pd.notna(row.get('kupujący')) else ''
    offer = str(row.get('oferta', ''))[:48] if pd.notna(row.get('oferta')) else ''
    print(f"{str(row['data']):<20} {buyer:<40} {offer:<50} {row['kwota_num']:>10,.2f}")

# ============================================================================
# Oplaty - szczegoly
# ============================================================================
print("\n\n### PROWIZJE I OPLATY - ROZBICIE ###\n")

oplaty = ops[ops['operacja'].str.contains('pobranie opłat', case=False, na=False)]

# Spróbuj parsowac szczegoly operacji
print(f"Laczna liczba opłat: {len(oplaty)}")
print(f"Laczna suma opłat: {oplaty['kwota_num'].sum():,.2f} PLN")

oplaty_mar = oplaty[oplaty['data_parsed'] >= '2026-03-01']
oplaty_feb = oplaty[oplaty['data_parsed'] < '2026-03-01']

print(f"\nMarzec (1-16): {len(oplaty_mar)} opłat, suma: {oplaty_mar['kwota_num'].sum():,.2f} PLN")
print(f"Luty (13-28): {len(oplaty_feb)} opłat, suma: {oplaty_feb['kwota_num'].sum():,.2f} PLN")

# ============================================================================
# Zwroty - szczegoly
# ============================================================================
print("\n\n### ZWROTY FINANSOWE ###\n")

zwroty = ops[ops['operacja'] == 'zwrot']
print(f"Liczba zwrotów: {len(zwroty)}")
print(f"Suma zwrotów: {zwroty['kwota_num'].sum():,.2f} PLN")

zwroty_mar = zwroty[zwroty['data_parsed'] >= '2026-03-01']
zwroty_feb = zwroty[zwroty['data_parsed'] < '2026-03-01']
print(f"\nMarzec: {len(zwroty_mar)} zwrotów, suma: {zwroty_mar['kwota_num'].sum():,.2f} PLN")
print(f"Luty (od 13): {len(zwroty_feb)} zwrotów, suma: {zwroty_feb['kwota_num'].sum():,.2f} PLN")

# ============================================================================
# Wypłaty
# ============================================================================
print("\n\n### WYPLATY ZE SRODKOW ###\n")

wyplaty = ops[ops['operacja'].str.contains('wypłata', case=False, na=False)]
print(f"Liczba wypłat: {len(wyplaty)}")
print(f"Suma wypłat: {wyplaty['kwota_num'].sum():,.2f} PLN")

for _, row in wyplaty.iterrows():
    print(f"  {row['data']}: {row['kwota_num']:,.2f} PLN")

# ============================================================================
# STATYSTYKI OFERT LUTY - poglebiona analiza
# ============================================================================
print("\n\n" + "=" * 80)
print("  STATYSTYKI OFERT REKLAMOWYCH - LUTY (1-24)")
print("=" * 80)

OFFERS_XLSX = r"c:\Users\sucho\Downloads\statystyki_oferty_01-02-2026_24-02-2026 (1).xlsx"
offers = pd.read_excel(OFFERS_XLSX)

# Oferty z kliknięciami
with_clicks = offers[offers['Kliknięcia'] > 0].sort_values('Kliknięcia', ascending=False)
print(f"\n### Oferty z kliknięciami (luty) ###\n")
print(f"{'Tytul oferty':<55} {'Wysw.':<8} {'Klik.':<8} {'CTR':<8} {'Koszt':<10} {'ROAS':<8} {'Szt.':<6} {'Sprz.PLN':<10}")
print("-" * 113)
for _, row in with_clicks.iterrows():
    title = str(row['Tytuł klikniętej oferty'])[:53]
    print(f"{title:<55} {row['Wyświetlenia']:<8} {row['Kliknięcia']:<8} {row['CTR']:<8.4f} {row['Koszt(PLN)']:<10.2f} {row['ROAS(PLN)']:<8.1f} {row['Liczba sprzedanych sztuk']:<6} {row['Wartość sprzedaży(PLN)']:<10.2f}")

# Oferty ze sprzedażą
with_sales = offers[offers['Liczba sprzedanych sztuk'] > 0].sort_values('Wartość sprzedaży(PLN)', ascending=False)
print(f"\n\n### Oferty ze sprzedaza z reklam (luty) ###\n")
print(f"{'Tytul oferty':<55} {'Szt.':<6} {'Sprz.PLN':<12} {'Koszt PLN':<12} {'ROAS':<8} {'CPC':<8}")
print("-" * 101)
for _, row in with_sales.iterrows():
    title = str(row['Tytuł klikniętej oferty'])[:53]
    print(f"{title:<55} {row['Liczba sprzedanych sztuk']:<6} {row['Wartość sprzedaży(PLN)']:<12.2f} {row['Koszt(PLN)']:<12.2f} {row['ROAS(PLN)']:<8.1f} {row['CPC(PLN)']:<8.2f}")

# Sumy kampanii luty
print(f"\n\n### PODSUMOWANIE KAMPANII REKLAMOWYCH LUTY ###\n")
total_views = offers['Wyświetlenia'].sum()
total_clicks = offers['Kliknięcia'].sum()
total_cost = offers['Koszt(PLN)'].sum()
total_sales_units = offers['Liczba sprzedanych sztuk'].sum()
total_sales_value = offers['Wartość sprzedaży(PLN)'].sum()
overall_ctr = total_clicks / total_views * 100 if total_views > 0 else 0
overall_roas = total_sales_value / total_cost if total_cost > 0 else 0
overall_cpc = total_cost / total_clicks if total_clicks > 0 else 0

print(f"  Wyswietlenia:           {total_views:>10,}")
print(f"  Klikniecia:             {total_clicks:>10,}")
print(f"  CTR:                    {overall_ctr:>10.2f}%")
print(f"  CPC:                    {overall_cpc:>10.2f} PLN")
print(f"  Koszt kampanii:         {total_cost:>10,.2f} PLN")
print(f"  Sprzedane szt:          {total_sales_units:>10,}")
print(f"  Wartosc sprzedazy:      {total_sales_value:>10,.2f} PLN")
print(f"  ROAS:                   {overall_roas:>10.2f}")

# POROWNANIE MARZEC vs LUTY (kampanie)
print(f"\n\n### POROWNANIE KAMPANII: MARZEC (1-15) vs LUTY (1-24) ###\n")

CAMPAIGN_XLSX = r"c:\Users\sucho\Downloads\statystyki_kampanie_01-03-2026_15-03-2026.xlsx"
campaigns = pd.read_excel(CAMPAIGN_XLSX)

mar_views = campaigns['Wyświetlenia'].sum()
mar_clicks = campaigns['Kliknięcia'].sum()
mar_cost = campaigns['Koszt(PLN)'].sum()
mar_sales_units = campaigns['Liczba sprzedanych sztuk'].sum()
mar_sales_value = campaigns['Wartość sprzedaży(PLN)'].sum()
mar_ctr = mar_clicks / mar_views * 100 if mar_views > 0 else 0
mar_roas = mar_sales_value / mar_cost if mar_cost > 0 else 0
mar_cpc = mar_cost / mar_clicks if mar_clicks > 0 else 0

print(f"{'Metryka':<30} {'Marzec (1-15)':<18} {'Luty (1-24)':<18}")
print("-" * 66)
print(f"{'Wyswietlenia':<30} {mar_views:<18,} {total_views:<18,}")
print(f"{'Klikniecia':<30} {mar_clicks:<18,} {total_clicks:<18,}")
print(f"{'CTR':<30} {mar_ctr:<18.2f}% {overall_ctr:<18.2f}%")
print(f"{'CPC (PLN)':<30} {mar_cpc:<18.2f} {overall_cpc:<18.2f}")
print(f"{'Koszt (PLN)':<30} {mar_cost:<18,.2f} {total_cost:<18,.2f}")
print(f"{'Sprzedane szt.':<30} {mar_sales_units:<18,} {total_sales_units:<18,}")
print(f"{'Wartosc sprzedazy (PLN)':<30} {mar_sales_value:<18,.2f} {total_sales_value:<18,.2f}")
print(f"{'ROAS':<30} {mar_roas:<18.2f} {overall_roas:<18.2f}")

# Dzienny koszt kampanii
mar_camp_days = 15
feb_camp_days = 24
print(f"\n{'Dzienny koszt reklam (PLN)':<30} {mar_cost/mar_camp_days:<18,.2f} {total_cost/feb_camp_days:<18,.2f}")
print(f"{'Dzienna sprz. z reklam (PLN)':<30} {mar_sales_value/mar_camp_days:<18,.2f} {total_sales_value/feb_camp_days:<18,.2f}")

print("\n\n" + "=" * 80)
print("  KONIEC DODATKOWEJ EKSTRAKCJI")
print("=" * 80)
