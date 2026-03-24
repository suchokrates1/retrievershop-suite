"""
Analiza marketingowa - marzec 2026 vs. luty 2026
Retriever Shop (Allegro)
"""
import sqlite3
import pandas as pd
import json
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = r"C:\Users\sucho\retrievershop_analysis.db"
CAMPAIGN_XLSX = r"c:\Users\sucho\Downloads\statystyki_kampanie_01-03-2026_15-03-2026.xlsx"
OFFERS_XLSX = r"c:\Users\sucho\Downloads\statystyki_oferty_01-02-2026_24-02-2026 (1).xlsx"
OPERATIONS_XLSX = r"c:\Users\sucho\Downloads\2026-02-13_2026-03-16_872352211_operations_all.xlsx"

# Zakresy dat (unix timestamp)
MAR_START = int(datetime(2026, 3, 1, tzinfo=timezone.utc).timestamp())
MAR_END = int(datetime(2026, 3, 16, tzinfo=timezone.utc).timestamp())
FEB_START = int(datetime(2026, 2, 1, tzinfo=timezone.utc).timestamp())
FEB_END = int(datetime(2026, 2, 28, 23, 59, 59, tzinfo=timezone.utc).timestamp())
# Pelny luty do porownania dniowego
FEB_DAYS = 28
MAR_DAYS = 15  # dane do 15 marca

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

print("=" * 80)
print("  ANALIZA MARKETINGOWA - MARZEC 2026 (1-15) vs LUTY 2026")
print("  Retriever Shop - Allegro")
print("=" * 80)

# ============================================================================
# 1. ZAMOWIENIA - wolumen i przychody
# ============================================================================
print("\n\n### 1. ZAMOWIENIA ###\n")

# Marzec 1-15
mar_orders = pd.read_sql_query(f"""
    SELECT o.order_id, o.external_order_id, o.date_add, o.payment_done, 
           o.delivery_price, o.customer_name, o.platform, o.delivery_method,
           o.user_login
    FROM orders o
    WHERE o.date_add >= {MAR_START} AND o.date_add < {MAR_END}
""", conn)

# Luty
feb_orders = pd.read_sql_query(f"""
    SELECT o.order_id, o.external_order_id, o.date_add, o.payment_done,
           o.delivery_price, o.customer_name, o.platform, o.delivery_method,
           o.user_login
    FROM orders o
    WHERE o.date_add >= {FEB_START} AND o.date_add < {FEB_END}
""", conn)

# Produkty zamowien
mar_products = pd.read_sql_query(f"""
    SELECT op.order_id, op.name, op.quantity, op.price_brutto, op.ean, op.sku
    FROM order_products op
    JOIN orders o ON op.order_id = o.order_id
    WHERE o.date_add >= {MAR_START} AND o.date_add < {MAR_END}
""", conn)

feb_products = pd.read_sql_query(f"""
    SELECT op.order_id, op.name, op.quantity, op.price_brutto, op.ean, op.sku
    FROM order_products op
    JOIN orders o ON op.order_id = o.order_id
    WHERE o.date_add >= {FEB_START} AND o.date_add < {FEB_END}
""", conn)

# Obliczenia
mar_order_count = len(mar_orders)
feb_order_count = len(feb_orders)

mar_revenue = (mar_products['price_brutto'].astype(float) * mar_products['quantity'].astype(float)).sum()
feb_revenue = (feb_products['price_brutto'].astype(float) * feb_products['quantity'].astype(float)).sum()

mar_items = mar_products['quantity'].astype(float).sum()
feb_items = feb_products['quantity'].astype(float).sum()

mar_avg_order = mar_revenue / mar_order_count if mar_order_count > 0 else 0
feb_avg_order = feb_revenue / feb_order_count if feb_order_count > 0 else 0

# Srednia dzienna
mar_daily_orders = mar_order_count / MAR_DAYS
feb_daily_orders = feb_order_count / FEB_DAYS
mar_daily_revenue = mar_revenue / MAR_DAYS
feb_daily_revenue = feb_revenue / FEB_DAYS

print(f"{'Metryka':<35} {'Marzec (1-15)':<20} {'Luty':<20} {'Zmiana %':<15}")
print("-" * 90)
print(f"{'Liczba zamowien':<35} {mar_order_count:<20} {feb_order_count:<20} {((mar_order_count/feb_order_count)-1)*100 if feb_order_count else 0:+.1f}%")
print(f"{'Srednia dzienna zamowien':<35} {mar_daily_orders:<20.1f} {feb_daily_orders:<20.1f} {((mar_daily_orders/feb_daily_orders)-1)*100 if feb_daily_orders else 0:+.1f}%")
print(f"{'Przychod brutto (PLN)':<35} {mar_revenue:<20,.2f} {feb_revenue:<20,.2f} {((mar_revenue/feb_revenue)-1)*100 if feb_revenue else 0:+.1f}%")
print(f"{'Sredni dzienny przychod (PLN)':<35} {mar_daily_revenue:<20,.2f} {feb_daily_revenue:<20,.2f} {((mar_daily_revenue/feb_daily_revenue)-1)*100 if feb_daily_revenue else 0:+.1f}%")
print(f"{'Sprzedane sztuki':<35} {mar_items:<20.0f} {feb_items:<20.0f} {((mar_items/feb_items)-1)*100 if feb_items else 0:+.1f}%")
print(f"{'Srednia wartosc zamowienia (PLN)':<35} {mar_avg_order:<20,.2f} {feb_avg_order:<20,.2f} {((mar_avg_order/feb_avg_order)-1)*100 if feb_avg_order else 0:+.1f}%")
print(f"{'Szt. na zamowienie':<35} {mar_items/mar_order_count if mar_order_count else 0:<20.2f} {feb_items/feb_order_count if feb_order_count else 0:<20.2f}")

# ============================================================================
# 2. SPRZEDAZ DZIENNIE - trend
# ============================================================================
print("\n\n### 2. TREND DZIENNY - MARZEC ###\n")

mar_orders_daily = pd.read_sql_query(f"""
    SELECT date(date_add, 'unixepoch') as day, COUNT(*) as cnt
    FROM orders
    WHERE date_add >= {MAR_START} AND date_add < {MAR_END}
    GROUP BY day ORDER BY day
""", conn)

mar_revenue_daily = pd.read_sql_query(f"""
    SELECT date(o.date_add, 'unixepoch') as day, 
           SUM(op.price_brutto * op.quantity) as revenue,
           SUM(op.quantity) as items
    FROM orders o
    JOIN order_products op ON o.order_id = op.order_id
    WHERE o.date_add >= {MAR_START} AND o.date_add < {MAR_END}
    GROUP BY day ORDER BY day
""", conn)

print(f"{'Data':<15} {'Zamowienia':<15} {'Przychod PLN':<18} {'Sztuki':<10}")
print("-" * 58)
for _, row in mar_revenue_daily.iterrows():
    orders_day = mar_orders_daily[mar_orders_daily['day'] == row['day']]['cnt'].values
    cnt = orders_day[0] if len(orders_day) > 0 else 0
    print(f"{row['day']:<15} {cnt:<15} {row['revenue']:<18,.2f} {int(row['items']):<10}")

# ============================================================================
# 3. TOP PRODUKTY
# ============================================================================
print("\n\n### 3. TOP PRODUKTY - MARZEC (1-15) ###\n")

mar_top = pd.read_sql_query(f"""
    SELECT op.name, SUM(op.quantity) as qty, SUM(op.price_brutto * op.quantity) as revenue,
           COUNT(DISTINCT op.order_id) as orders_cnt
    FROM order_products op
    JOIN orders o ON op.order_id = o.order_id
    WHERE o.date_add >= {MAR_START} AND o.date_add < {MAR_END}
    GROUP BY op.name
    ORDER BY revenue DESC
    LIMIT 25
""", conn)

print(f"{'#':<4} {'Produkt':<60} {'Szt':<8} {'Przychod PLN':<15} {'Zamow.':<8}")
print("-" * 95)
for i, row in mar_top.iterrows():
    print(f"{i+1:<4} {row['name'][:58]:<60} {int(row['qty']):<8} {row['revenue']:<15,.2f} {int(row['orders_cnt']):<8}")

# Porownanie top produktow luty vs marzec
print("\n\n### 3b. POROWNANIE TOP PRODUKTOW - MARZEC vs LUTY ###\n")

feb_top = pd.read_sql_query(f"""
    SELECT op.name, SUM(op.quantity) as qty, SUM(op.price_brutto * op.quantity) as revenue
    FROM order_products op
    JOIN orders o ON op.order_id = o.order_id
    WHERE o.date_add >= {FEB_START} AND o.date_add < {FEB_END}
    GROUP BY op.name
    ORDER BY revenue DESC
""", conn)

# Merge
comparison = mar_top[['name', 'qty', 'revenue']].merge(
    feb_top[['name', 'qty', 'revenue']], on='name', how='left', suffixes=('_mar', '_feb')
)
comparison = comparison.fillna(0)

print(f"{'Produkt':<55} {'Mar szt':<10} {'Lut szt':<10} {'Mar PLN':<12} {'Lut PLN':<12}")
print("-" * 99)
for _, row in comparison.iterrows():
    print(f"{row['name'][:53]:<55} {int(row['qty_mar']):<10} {int(row['qty_feb']):<10} {row['revenue_mar']:<12,.2f} {row['revenue_feb']:<12,.2f}")

# ============================================================================
# 4. MARZA - tabela Sales
# ============================================================================
print("\n\n### 4. MARZA I RENTOWNOSC ###\n")

mar_sales = pd.read_sql_query("""
    SELECT * FROM sales
    WHERE sale_date >= '2026-03-01' AND sale_date <= '2026-03-15'
""", conn)

feb_sales = pd.read_sql_query("""
    SELECT * FROM sales
    WHERE sale_date >= '2026-02-01' AND sale_date <= '2026-02-28'
""", conn)

for label, df in [("MARZEC (1-15)", mar_sales), ("LUTY", feb_sales)]:
    if df.empty:
        print(f"\n{label}: Brak rekordow w tabeli sales")
        continue
    df['sale_price'] = df['sale_price'].astype(float)
    df['purchase_cost'] = df['purchase_cost'].astype(float)
    df['shipping_cost'] = df['shipping_cost'].astype(float)
    df['commission_fee'] = df['commission_fee'].astype(float)
    df['margin'] = df['sale_price'] - df['purchase_cost'] - df['shipping_cost'] - df['commission_fee']
    
    total_revenue = df['sale_price'].sum()
    total_cost = df['purchase_cost'].sum()
    total_shipping = df['shipping_cost'].sum()
    total_commission = df['commission_fee'].sum()
    total_margin = df['margin'].sum()
    margin_pct = (total_margin / total_revenue * 100) if total_revenue > 0 else 0
    
    print(f"\n--- {label} ---")
    print(f"  Przychod ze sprzedazy:  {total_revenue:>12,.2f} PLN")
    print(f"  Koszt zakupu:           {total_cost:>12,.2f} PLN")
    print(f"  Koszt wysylki:          {total_shipping:>12,.2f} PLN")
    print(f"  Prowizja Allegro:       {total_commission:>12,.2f} PLN")
    print(f"  MARZA NETTO:            {total_margin:>12,.2f} PLN")
    print(f"  Marza %:                {margin_pct:>12.1f}%")
    print(f"  Liczba transakcji:      {len(df):>12}")

# ============================================================================
# 5. KOSZTY STALE
# ============================================================================
print("\n\n### 5. KOSZTY STALE ###\n")

fixed_costs = pd.read_sql_query("SELECT * FROM fixed_costs WHERE is_active = 1", conn)
if not fixed_costs.empty:
    print(f"{'Nazwa':<40} {'Kwota PLN':<15}")
    print("-" * 55)
    total_fixed = 0
    for _, row in fixed_costs.iterrows():
        amt = float(row['amount'])
        total_fixed += amt
        print(f"{row['name']:<40} {amt:<15,.2f}")
    print(f"\n{'SUMA miesieczna':<40} {total_fixed:<15,.2f}")
else:
    print("Brak aktywnych kosztow stalych w bazie.")

# ============================================================================
# 6. ZWROTY
# ============================================================================
print("\n\n### 6. ZWROTY ###\n")

mar_returns = pd.read_sql_query(f"""
    SELECT r.*, o.date_add
    FROM returns r
    LEFT JOIN orders o ON r.order_id = o.order_id
    WHERE r.created_at >= '2026-03-01' AND r.created_at <= '2026-03-15'
""", conn)

feb_returns = pd.read_sql_query(f"""
    SELECT r.*, o.date_add
    FROM returns r
    LEFT JOIN orders o ON r.order_id = o.order_id
    WHERE r.created_at >= '2026-02-01' AND r.created_at <= '2026-02-28'
""", conn)

print(f"{'Metryka':<35} {'Marzec (1-15)':<20} {'Luty':<20}")
print("-" * 75)
print(f"{'Liczba zwrotow':<35} {len(mar_returns):<20} {len(feb_returns):<20}")
if mar_order_count > 0 and feb_order_count > 0:
    print(f"{'Stopa zwrotow %':<35} {len(mar_returns)/mar_order_count*100:<20.1f} {len(feb_returns)/feb_order_count*100:<20.1f}")

# Szczegoly zwrotow
for label, df in [("MARZEC", mar_returns), ("LUTY", feb_returns)]:
    if not df.empty:
        status_counts = df['status'].value_counts()
        print(f"\n  {label} - statusy zwrotow:")
        for status, cnt in status_counts.items():
            print(f"    {status}: {cnt}")

# ============================================================================
# 7. METODY DOSTAWY
# ============================================================================
print("\n\n### 7. METODY DOSTAWY ###\n")

mar_delivery = pd.read_sql_query(f"""
    SELECT delivery_method, COUNT(*) as cnt
    FROM orders
    WHERE date_add >= {MAR_START} AND date_add < {MAR_END}
    GROUP BY delivery_method
    ORDER BY cnt DESC
""", conn)

print(f"{'Metoda dostawy':<50} {'Zamowienia':<15} {'Udzial %':<10}")
print("-" * 75)
for _, row in mar_delivery.iterrows():
    pct = row['cnt'] / mar_order_count * 100 if mar_order_count > 0 else 0
    print(f"{str(row['delivery_method'])[:48]:<50} {row['cnt']:<15} {pct:.1f}%")

# ============================================================================
# 8. POZYCJA CENOWA - ostatni raport
# ============================================================================
print("\n\n### 8. POZYCJA CENOWA (ost. raport) ###\n")

price_report = pd.read_sql_query("""
    SELECT pri.*, pr.created_at as report_date
    FROM price_report_items pri
    JOIN price_reports pr ON pri.report_id = pr.id
    WHERE pr.id = (SELECT MAX(id) FROM price_reports WHERE status='completed')
    ORDER BY pri.price_difference DESC
""", conn)

if not price_report.empty:
    cheapest_count = price_report['is_cheapest'].sum()
    total_checked = len(price_report)
    avg_position = price_report['our_position'].mean()
    
    print(f"Data raportu: {price_report['report_date'].iloc[0]}")
    print(f"Ofert sprawdzonych: {total_checked}")
    print(f"Najtansi: {cheapest_count} ({cheapest_count/total_checked*100:.1f}%)")
    print(f"Srednia pozycja cenowa: {avg_position:.1f}")
    
    # Oferty gdzie NIE jestesmy najtansi
    not_cheapest = price_report[price_report['is_cheapest'] == 0].head(15)
    if not not_cheapest.empty:
        print(f"\nOferty z wyzsza cena niz konkurencja (top 15):")
        print(f"{'Produkt':<50} {'Nasza':<10} {'Konk.':<10} {'Roznica':<10} {'Poz.':<6}")
        print("-" * 86)
        for _, row in not_cheapest.iterrows():
            print(f"{str(row['product_name'])[:48]:<50} {row['our_price']:<10} {row['competitor_price']:<10} {row['price_difference']:<10} {row['our_position']:<6}")
else:
    print("Brak ukonczonego raportu cenowego w bazie.")

# ============================================================================
# 9. HISTORIA CEN KONKURENCJI
# ============================================================================
print("\n\n### 9. HISTORIA CEN KONKURENCJI (ostatnie 45 dni) ###\n")

price_history = pd.read_sql_query("""
    SELECT aph.recorded_at, aph.price, aph.competitor_price, aph.competitor_seller,
           ps.size, p.name as product_name, p.category, p.series
    FROM allegro_price_history aph
    JOIN product_sizes ps ON aph.product_size_id = ps.id
    JOIN products p ON ps.product_id = p.id
    WHERE aph.recorded_at >= datetime('now', '-45 days')
    AND aph.competitor_price IS NOT NULL
    ORDER BY aph.recorded_at DESC
""", conn)

if not price_history.empty:
    print(f"Rekordow z danymi konkurencji: {len(price_history)}")
    
    # Glowni konkurenci
    if 'competitor_seller' in price_history.columns:
        top_competitors = price_history['competitor_seller'].value_counts().head(10)
        print(f"\nNajczesciej spotykani konkurenci:")
        for seller, cnt in top_competitors.items():
            print(f"  {seller}: {cnt} ofert")
else:
    print("Brak historii cen konkurencji w ostatnich 45 dniach.")

# ============================================================================
# 10. ALLEGRO OFERTY - Stan
# ============================================================================
print("\n\n### 10. AKTYWNE OFERTY ALLEGRO ###\n")

offers_status = pd.read_sql_query("""
    SELECT publication_status, COUNT(*) as cnt
    FROM allegro_offers
    GROUP BY publication_status
""", conn)

if not offers_status.empty:
    print(f"{'Status':<20} {'Liczba':<10}")
    print("-" * 30)
    for _, row in offers_status.iterrows():
        print(f"{row['publication_status']:<20} {row['cnt']:<10}")

# Stan magazynowy
print("\n\n### 11. STAN MAGAZYNOWY ###\n")

stock = pd.read_sql_query("""
    SELECT p.name as product_name, p.category, p.series, 
           ps.size, ps.quantity
    FROM product_sizes ps
    JOIN products p ON ps.product_id = p.id
    WHERE ps.quantity > 0
    ORDER BY ps.quantity DESC
""", conn)

if not stock.empty:
    total_stock = stock['quantity'].sum()
    print(f"Calkowity stan: {total_stock:.0f} szt.")
    print(f"Pozycji z zapasem: {len(stock)}")
    
    # Zero stock
    zero_stock = pd.read_sql_query("""
        SELECT COUNT(*) as cnt FROM product_sizes WHERE quantity = 0
    """, conn)
    print(f"Pozycji z zerem: {zero_stock['cnt'].iloc[0]}")

# Unikalni klienci
print("\n\n### 12. UNIKALNI KLIENCI ###\n")

mar_unique = pd.read_sql_query(f"""
    SELECT COUNT(DISTINCT user_login) as unique_buyers
    FROM orders
    WHERE date_add >= {MAR_START} AND date_add < {MAR_END}
    AND user_login IS NOT NULL AND user_login != ''
""", conn)

feb_unique = pd.read_sql_query(f"""
    SELECT COUNT(DISTINCT user_login) as unique_buyers
    FROM orders
    WHERE date_add >= {FEB_START} AND date_add < {FEB_END}
    AND user_login IS NOT NULL AND user_login != ''
""", conn)

# Powracajacy klienci
returning = pd.read_sql_query(f"""
    SELECT user_login, COUNT(*) as order_count
    FROM orders
    WHERE date_add >= {MAR_START} AND date_add < {MAR_END}
    AND user_login IS NOT NULL AND user_login != ''
    GROUP BY user_login
    HAVING order_count > 1
""", conn)

print(f"{'Metryka':<35} {'Marzec (1-15)':<20} {'Luty':<20}")
print("-" * 75)
print(f"{'Unikalni kupujacy':<35} {mar_unique['unique_buyers'].iloc[0]:<20} {feb_unique['unique_buyers'].iloc[0]:<20}")
print(f"{'Powracajacy (>1 zamowienie)':<35} {len(returning):<20}")

# Dlugoterminowy trend
print("\n\n### 13. TREND MIESIECZNY (ostatnie 6 miesiecy) ###\n")

monthly_trend = pd.read_sql_query("""
    SELECT strftime('%Y-%m', date_add, 'unixepoch') as month,
           COUNT(*) as orders,
           COUNT(DISTINCT user_login) as unique_buyers
    FROM orders
    WHERE date_add >= strftime('%s', 'now', '-180 days')
    GROUP BY month
    ORDER BY month
""", conn)

monthly_revenue = pd.read_sql_query("""
    SELECT strftime('%Y-%m', o.date_add, 'unixepoch') as month,
           SUM(op.price_brutto * op.quantity) as revenue,
           SUM(op.quantity) as items
    FROM orders o
    JOIN order_products op ON o.order_id = op.order_id
    WHERE o.date_add >= strftime('%s', 'now', '-180 days')
    GROUP BY month
    ORDER BY month
""", conn)

merged_trend = monthly_trend.merge(monthly_revenue, on='month', how='left')

print(f"{'Miesiac':<12} {'Zamowienia':<15} {'Przychod PLN':<18} {'Szt.':<10} {'Unikaln.':<12}")
print("-" * 67)
for _, row in merged_trend.iterrows():
    print(f"{row['month']:<12} {row['orders']:<15} {row.get('revenue', 0):<18,.2f} {int(row.get('items', 0)):<10} {row['unique_buyers']:<12}")

# ============================================================================
# EXCEL: KAMPANIE REKLAMOWE
# ============================================================================
print("\n\n" + "=" * 80)
print("  DANE Z PLIKOW EXCEL")
print("=" * 80)

print("\n\n### 14. STATYSTYKI KAMPANII (1-15 marzec 2026) ###\n")
try:
    campaigns = pd.read_excel(CAMPAIGN_XLSX)
    print(f"Kolumny: {list(campaigns.columns)}")
    print(f"Wierszy: {len(campaigns)}")
    print(f"\nPelne dane:")
    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', 200)
    pd.set_option('display.max_colwidth', 40)
    print(campaigns.to_string(index=False))
    
    # Podsumowanie
    numeric_cols = campaigns.select_dtypes(include=['number']).columns
    if len(numeric_cols) > 0:
        print(f"\n\nPodsumowanie numeryczne:")
        print(campaigns[numeric_cols].describe().to_string())
except Exception as e:
    print(f"Blad odczytu kampanii: {e}")

print("\n\n### 15. STATYSTYKI OFERT (1-24 luty 2026) ###\n")
try:
    offers = pd.read_excel(OFFERS_XLSX)
    print(f"Kolumny: {list(offers.columns)}")
    print(f"Wierszy: {len(offers)}")
    
    # Pokaz top 30 wierszy
    print(f"\nTop 30 ofert:")
    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', 200)
    pd.set_option('display.max_colwidth', 50)
    print(offers.head(30).to_string(index=False))
    
    numeric_cols = offers.select_dtypes(include=['number']).columns
    if len(numeric_cols) > 0:
        print(f"\n\nPodsumowanie numeryczne:")
        print(offers[numeric_cols].sum().to_string())
except Exception as e:
    print(f"Blad odczytu ofert: {e}")

print("\n\n### 16. OPERACJE FINANSOWE (13.02-16.03) ###\n")
try:
    # Moze miec wiele arkuszy
    xls = pd.ExcelFile(OPERATIONS_XLSX)
    print(f"Arkusze: {xls.sheet_names}")
    
    for sheet in xls.sheet_names:
        df = pd.read_excel(OPERATIONS_XLSX, sheet_name=sheet)
        print(f"\n--- Arkusz: {sheet} ---")
        print(f"Kolumny: {list(df.columns)}")
        print(f"Wierszy: {len(df)}")
        
        # Pokaz pierwsze i ostatnie wiersze
        print(f"\nPierwsze 5:")
        print(df.head(5).to_string(index=False))
        
        numeric_cols = df.select_dtypes(include=['number']).columns
        if len(numeric_cols) > 0:
            print(f"\nSumy:")
            print(df[numeric_cols].sum().to_string())
            
        # Jesli sa kolumny z typem operacji - podsumuj
        str_cols = df.select_dtypes(include=['object']).columns
        for col in str_cols:
            unique_count = df[col].nunique()
            if 2 <= unique_count <= 20:
                print(f"\nRozbicie po '{col}':")
                grouped = df.groupby(col)[numeric_cols].sum() if len(numeric_cols) > 0 else df[col].value_counts()
                print(grouped.to_string())

except Exception as e:
    print(f"Blad odczytu operacji: {e}")

conn.close()

print("\n\n" + "=" * 80)
print("  KONIEC EKSTRAKCJI DANYCH")
print("=" * 80)
