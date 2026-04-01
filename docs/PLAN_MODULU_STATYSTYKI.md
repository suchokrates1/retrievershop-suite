# Plan wdrozenia modulu Statystyki

## 1. Cel biznesowy

Celem nowego modulu Statystyki jest zbudowanie jednej, spojnej zakladki analitycznej do zarzadzania sprzedaza i rentownoscia sklepu. Modul ma odpowiadac na pytania:

1. Ile realnie zarabiamy miesiac do miesiaca.
2. Ktore produkty i oferty napedzaja wynik, a ktore go obnizaja.
3. Jakie koszty Allegro i reklamy zjadaja marze.
4. Czy zwroty i logistyka pogarszaja wynik finansowy.
5. Jak nasza cena i pozycja wobec konkurencji wplywa na obrot.

Modul ma byc praktyczny decyzyjnie, nie tylko raportowy.

## 2. Zakres modulu

### 2.1 Zakres funkcjonalny

1. Dashboard glowny KPI z porownaniem do poprzednich okresow.
2. Analiza sprzedazy i obrotu.
3. Analiza zysku i kosztow.
4. Analiza kosztow Allegro i reklam.
5. Analiza zwrotow i refundacji.
6. Analiza logistyki i czasu realizacji.
7. Analiza produktowa i magazynowa.
8. Analiza cen i pozycji konkurencyjnej.
9. Alerty i wykrywanie anomalii.
10. Eksport danych i raporty okresowe.

### 2.2 Zakres danych

Modul laczy dane z:

1. Lokalnej bazy (zamowienia, produkty, statusy, zwroty, koszty stale, ceny i konkurencja).
2. Integracji Allegro (orders, billing/financial operations, returns, promotions, tracking, dane ofertowe).

## 3. Inwentaryzacja danych dostepnych juz teraz

### 3.1 Sprzedaz i zamowienia

Dostepne dane:

1. Zamowienie: order_id, platforma, metody platnosci, COD, payment_done, delivery_price, daty, adresy, dane wysylki.
2. Pozycje zamowien: nazwa, ilosc, cena brutto, auction_id, ean, mapowanie do product_size.
3. Historia statusow: pobrano, nieoplacone, wydrukowano, spakowano, wyslano, dostarczono, blad_druku, zwrot.

Wniosek analityczny:

1. Mozna liczyc obrot, AOV, wolumen, dynamike statusow i lead time operacyjny.

### 3.2 Finanse i marza

Dostepne dane:

1. Kalkulator finansowy order-level i period-level.
2. Koszt zakupu po powiazaniu z PurchaseBatch.
3. Koszt pakowania.
4. Koszty stale.
5. Korekty dla zamowien COD (sprzedaz liczona jako suma pozycji + dostawa, a nie tylko payment_done).

Wniosek analityczny:

1. Mozna raportowac zysk brutto/netto i marze na poziomie zamowienia, dnia, tygodnia i miesiaca.

### 3.3 Koszty Allegro i reklamy

Dostepne dane:

1. Integracja billing entries z podzialem na prowizje, listing fee, shipping fee, promo fee, bonusy.
2. Obsluga Ads NSP (koszt kampanii na poziomie konta).
3. Dostepne rozbicie oplat na szczegoly.

Wniosek analityczny:

1. Mozna liczyc koszt Allegro i koszt reklam jako procent przychodu oraz ich trend.

### 3.4 Zwroty

Dostepne dane:

1. Zwroty Allegro: statusy, powody, produkty, tracking paczki zwrotnej, przewoznik.
2. Historia statusow zwrotu.
3. Flagi stock_restored i refund_processed.

Wniosek analityczny:

1. Mozna liczyc wskaznik zwrotow ilosciowo i wartosciowo, czas zwrotu oraz wpływ zwrotow na marze.

### 3.5 Ceny i konkurencja

Dostepne dane:

1. Historia cen ofert i dane konkurencji.
2. Raporty cenowe: pozycja, roznica ceny, najtanszy konkurent, liczba ofert.
3. Integracja z aktualizacja cen i ponownym sprawdzaniem.

Wniosek analityczny:

1. Mozna budowac metryki konkurencyjnosci i korelacje ceny z wynikiem.

### 3.6 Magazyn

Dostepne dane:

1. Product, ProductSize, stany, barcode, low stock.
2. PurchaseBatch z remaining_quantity (potencjal pod FIFO).
3. Stocktake i skany.

Wniosek analityczny:

1. Mozna raportowac rotacje, wolnoobrot, braki i ryzyko stock-out.

## 4. Docelowe KPI

### 4.1 KPI zarzadcze (top cards)

1. Przychod brutto.
2. Przychod netto po zwrotach.
3. Zysk brutto.
4. Zysk netto po kosztach stalych i reklamach.
5. Marza procentowa.
6. Liczba zamowien.
7. Produkty sprzedane.
8. Srednia wartosc zamowienia.
9. Zwroty procentowo.
10. Koszt Allegro do przychodu.
11. Koszt Ads do przychodu.
12. Udzial COD i online.

### 4.2 KPI operacyjne

1. Czas od zamowienia do etykiety.
2. Czas od zamowienia do nadania.
3. Czas od nadania do doreczenia.
4. Udzial zamowien z opoznieniem SLA.
5. Odsetek zamowien z bledem drukowania/etykiety.

### 4.3 KPI produktowe

1. Top produkty po ilosci, przychodzie i zysku.
2. Produkty o najwyzszej marzy procentowej.
3. Produkty o ujemnej lub niskiej marzy.
4. Wolnoobrot i zaleganie magazynowe.
5. Rotacja stocku i prognoza dni do wyczerpania.

### 4.4 KPI konkurencyjne

1. Udzial ofert na pozycji 1.
2. Srednia roznica do najtanszej oferty.
3. Liczba ofert wymagajacych korekty ceny.
4. Wplyw zmiany ceny na wolumen i zysk.

## 5. Widoki i UX nowej zakladki

## 5.1 Sekcje zakladki

1. Overview.
2. Sprzedaz.
3. Zysk i koszty.
4. Allegro i reklamy.
5. Zwroty.
6. Logistyka.
7. Produkty i magazyn.
8. Ceny i konkurencja.
9. Alerty.
10. Eksport.

### 5.2 Komponenty UI

1. Pasek filtrow globalnych na gorze.
2. Karty KPI z delta (MoM, WoW, YoY).
3. Wykres trendu dziennego i tygodniowego.
4. Wykres waterfall od przychodu do zysku netto.
5. Tabele drill-down z filtrem i sortowaniem.
6. Widok porownania okres do okresu.
7. Tryb export-ready.

### 5.3 Typy wykresow

1. Linia: trend przychodu, zysku, marzy.
2. Slupki grupowane: okres obecny vs poprzedni.
3. Stack area: struktura kosztow.
4. Heatmapa: dzien tygodnia i godzina.
5. Pareto: produkty i udzial 80/20.
6. Scatter: marza vs wolumen.

## 6. Integracje Allegro pod statystyki

### 6.1 Obszary danych do pobrania

1. Zamowienia checkout-forms i status fulfillment.
2. Billing entries i financial operations (prowizje, listing, promo, shipping, bonusy, refunds).
3. Reklamy Ads (NSP) i koszty dzienne/miesieczne.
4. Customer returns i statusy zwrotow.
5. Dane dostaw i tracking.
6. Dane ofert i zdarzen ofertowych.
7. Dane promowan (aktywne, odnowienia, koszt).

### 6.2 Co juz mamy zaimplementowane

1. Order sync event-driven i fulfillment sync.
2. Billing summary dla zamowien.
3. Ads period cost.
4. Returns sync i tracking zwrotow.
5. Promotions summary.

### 6.3 Co uzupelnic

1. Dodatkowe endpointy finansowe do pelnej zgodnosci miesiecznych raportow.
2. Ujednolicenie mapowania statusow i kodow trackingowych.
3. Lepsze mapowanie kosztow reklam do osi czasu i kampanii.
4. Tabela surowych zdarzen analitycznych Allegro (raw ingest).

## 7. Architektura techniczna

### 7.1 Warstwa backend

1. Nowy blueprint: stats.
2. API read-only z parametrami filtrow.
3. Agregacja po stronie serwera.
4. Cache wynikow dla ciezkich zapytan.
5. Rate limiting i timeouty dla endpointow ciezkich.

### 7.2 Warstwa danych analitycznych

Proponowane tabele (warstwa analityczna):

1. fact_orders_daily.
2. fact_order_items_daily.
3. fact_costs_daily.
4. fact_returns_daily.
5. fact_ads_daily.
6. fact_offer_competition_daily.
7. dim_time.
8. dim_product.
9. dim_channel.
10. dim_delivery_method.

### 7.3 ETL

1. Inkrementalny ETL co 15-60 minut.
2. Snapshot dzienny.
3. Idempotentnosc i deduplikacja.
4. Watermark na timestampach i event_id.
5. Rebuild historyczny na zadanie.

### 7.4 Wydajnosc

1. Preagregacje dzienne i miesieczne.
2. Indeksy pod najczestsze filtry.
3. Lazy loading sekcji ciezkich.
4. Odseparowanie zapytan realtime od zapytan analitycznych.

## 8. Definicje metryk (wersja robocza)

### 8.1 Przychod

1. Dla online: payment_done.
2. Dla COD: suma pozycji + delivery_price.
3. Przychod netto: przychod minus wartosc zwrotow completed.

### 8.2 Zysk

1. Zysk brutto = przychod - koszty Allegro - koszt zakupu - koszt pakowania.
2. Zysk netto = zysk brutto - koszty stale - koszty reklam.

### 8.3 Marza

1. Marza procentowa = zysk brutto / przychod * 100.

### 8.4 Zwroty

1. Return rate ilosciowo = liczba zamowien ze zwrotem / liczba zamowien.
2. Return rate wartosciowo = wartosc zwrotow / przychod.

### 8.5 Konkurencja

1. Share of cheapest = liczba ofert, gdzie jestesmy najtansi / liczba ofert monitorowanych.
2. Srednia roznica ceny = srednia(our_price - competitor_price).

## 9. Plan wdrozenia etapami

### Etap 0: Analiza i specyfikacja (3-5 dni)

1. Uzgodnienie slownika KPI i definicji.
2. Lista raportow i widokow.
3. Mapa zrodel danych i ograniczen.
4. Prototyp low-fidelity UI.

### Etap 1: MVP Statystyki (2-3 tygodnie)

1. Zakladka Statystyki + filtry globalne.
2. Karty KPI.
3. Trend przychodu/zysku/marzy.
4. Porownanie MoM i WoW.
5. Podstawowy eksport CSV.

### Etap 2: Finanse i Allegro (2 tygodnie)

1. Rozbicie kosztow Allegro.
2. Koszty Ads dzien/miesiac.
3. Waterfall finansowy.
4. Zgodnosc raportowa z billingiem i zamowieniami.

### Etap 3: Zwroty i logistyka (2 tygodnie)

1. Dashboard zwrotow.
2. SLA i lead time realizacji.
3. Alerty operacyjne.
4. Drill-down do poziomu zamowienia.

### Etap 4: Produkty i konkurencja (2 tygodnie)

1. Top i low performers.
2. Rotacja i ryzyko stock-out.
3. Pozycja konkurencyjna i zmiany cen.
4. Wskazniki rekomendacji cen.

### Etap 5: Stabilizacja i automatyzacja (1-2 tygodnie)

1. Testy wydajnosciowe.
2. Monitoring i alerting.
3. Raporty automatyczne tygodniowe/miesieczne.
4. Finalne porzadkowanie UX.

## 10. API kontraktowe (propozycja)

1. GET /api/stats/overview
2. GET /api/stats/sales
3. GET /api/stats/profit
4. GET /api/stats/allegro-costs
5. GET /api/stats/returns
6. GET /api/stats/logistics
7. GET /api/stats/products
8. GET /api/stats/competition
9. GET /api/stats/alerts
10. GET /api/stats/export

Parametry wspolne:

1. date_from
2. date_to
3. granularity day/week/month
4. platform
5. payment_type cod/online/all
6. delivery_method
7. product_id or product_size_id

## 11. Testy i walidacja

### 11.1 Testy funkcjonalne

1. Poprawnosc KPI dla znanych probek danych.
2. Poprawnosc porownan MoM/WoW/YoY.
3. Poprawnosc filtrow i drill-down.

### 11.2 Testy danych

1. Walidacja zgodnosci revenue i billing.
2. Walidacja marzy order-level i period-level.
3. Walidacja zwrotow i refund_processed.

### 11.3 Testy niefunkcjonalne

1. Wydajnosc endpointow ciezkich.
2. Stabilnosc ETL.
3. Odpornosc na brak danych z Allegro.

## 12. Ryzyka i mitigacje

1. Braki lub opoznienia danych Allegro.
   - Mitigacja: cache, retry, oznaczanie confidence level metryk.
2. Niespojnosci czasowe i duplikaty zdarzen.
   - Mitigacja: watermark + deduplikacja po kluczach.
3. Rozjazdy definicji KPI miedzy raportami.
   - Mitigacja: jeden slownik metryk i testy kontraktowe.
4. Ciezkie zapytania na produkcji.
   - Mitigacja: preagregacje i lazy loading.

## 13. Backlog startowy (kolejnosc realizacji)

1. Spisanie finalnego slownika KPI i wzorow.
2. Migracje tabel analitycznych fact/dim.
3. ETL dzienny + inkrementalny.
4. Endpoint /api/stats/overview.
5. UI zakladki Statystyki z KPI i 4 wykresami.
6. Sekcja koszty Allegro i Ads.
7. Sekcja zwroty i logistyka.
8. Sekcja produkty i konkurencja.
9. Eksport CSV/XLSX.
10. Alerty i raport tygodniowy na Messenger.

## 14. Kryteria akceptacji MVP

1. Jeden ekran daje odpowiedz na: obrot, zysk, marza, zwroty, koszty Allegro i Ads.
2. Kazda metryka ma porownanie do poprzedniego okresu.
3. Uzytkownik moze zejsc do szczegolow po kliknieciu wykresu.
4. Dane laduja sie stabilnie i mieszcza sie w uzgodnionym czasie odpowiedzi.
5. Wyniki sa zgodne z kalkulacjami finansowymi systemu.

## 15. Rekomendacja realizacyjna

Najbezpieczniejsze podejscie to iteracyjne wdrozenie od MVP finansowo-sprzedazowego, a nastepnie dokladanie sekcji specjalistycznych (Allegro costs, zwroty, logistyka, konkurencja). Pozwoli to szybko oddac wartosc biznesowa i jednoczesnie utrzymac kontrolowana zlozonosc projektu.

## 16. Specyfikacja techniczna v1

### 16.1 Architektura endpointow

1. Wszystkie endpointy pod namespace `/api/stats/*`.
2. Odpowiedzi w formacie JSON z jednolitym envelope.
3. Dwie klasy endpointow:
    1. fast: do 300 ms (KPI i lekkie agregaty).
    2. heavy: do 2-5 s (trend, porownania, drill-down, duze zakresy dat).
4. Cache warstwowy:
    1. klucz cache = endpoint + zestaw filtrow.
    2. TTL fast = 60 s.
    3. TTL heavy = 300 s.

### 16.2 Ujednolicony format odpowiedzi

```json
{
   "ok": true,
   "generated_at": "2026-04-01T12:00:00Z",
   "filters": {
      "date_from": "2026-03-01",
      "date_to": "2026-03-31",
      "granularity": "day",
      "platform": "allegro",
      "payment_type": "all"
   },
   "data": {},
   "meta": {
      "confidence": "high",
      "sources": ["db.orders", "allegro.billing"],
      "cache": "hit"
   },
   "errors": []
}
```

### 16.3 Kontrakty endpointow v1

#### GET /api/stats/overview

Przeznaczenie:
1. top-karty KPI + delty MoM/WoW.

Minimalny payload `data`:

```json
{
   "kpi": {
      "revenue_gross": {"value": 123456.78, "mom": 12.4, "wow": 3.1},
      "profit_net": {"value": 23456.11, "mom": 9.2, "wow": -1.0},
      "margin_pct": {"value": 19.0, "mom": -0.7, "wow": 0.3},
      "orders_count": {"value": 642, "mom": 8.9, "wow": 2.2},
      "aov": {"value": 192.30, "mom": 1.8, "wow": 0.6},
      "returns_rate": {"value": 4.2, "mom": 0.5, "wow": -0.2},
      "allegro_cost_pct": {"value": 14.7, "mom": -0.3, "wow": 0.2},
      "ads_cost_pct": {"value": 3.4, "mom": 0.9, "wow": 0.1}
   }
}
```

#### GET /api/stats/sales

Przeznaczenie:
1. trend obrotu i wolumenu.

```json
{
   "series": [
      {"bucket": "2026-03-01", "revenue": 4123.44, "orders": 21, "items": 37}
   ],
   "split": {
      "payment": {"cod": 31.2, "online": 68.8},
      "platform": {"allegro": 100.0}
   }
}
```

#### GET /api/stats/profit

Przeznaczenie:
1. rentownosc i waterfall kosztowy.

```json
{
   "summary": {
      "revenue": 123456.78,
      "purchase_cost": 61234.11,
      "allegro_fees": 15432.90,
      "packaging_cost": 812.00,
      "fixed_costs": 3200.00,
      "ads_cost": 4200.50,
      "gross_profit": 46000.27,
      "net_profit": 38600.27,
      "margin_pct": 31.09
   },
   "waterfall": [
      {"name": "Przychod", "value": 123456.78},
      {"name": "Koszt towaru", "value": -61234.11},
      {"name": "Koszty Allegro", "value": -15432.90},
      {"name": "Pakowanie", "value": -812.00},
      {"name": "Ads", "value": -4200.50},
      {"name": "Koszty stale", "value": -3200.00},
      {"name": "Zysk netto", "value": 38600.27}
   ]
}
```

#### GET /api/stats/allegro-costs

Przeznaczenie:
1. szczegoly kosztow Allegro i Ads.

```json
{
   "fees_by_type": [
      {"type": "SUC", "name": "Prowizja organiczna", "amount": 8200.10},
      {"type": "BRG", "name": "Prowizja Ads", "amount": 2100.20},
      {"type": "FEA", "name": "Wyroznienia", "amount": 940.00},
      {"type": "NSP", "name": "Koszt kampanii Ads", "amount": 4200.50}
   ],
   "daily_ads": [
      {"date": "2026-03-01", "amount": 120.40}
   ],
   "totals": {
      "allegro_total": 15432.90,
      "ads_total": 4200.50,
      "allegro_pct_revenue": 12.50,
      "ads_pct_revenue": 3.40
   }
}
```

#### GET /api/stats/returns

Przeznaczenie:
1. monitoring zwrotow i refundacji.

```json
{
   "summary": {
      "returns_count": 28,
      "returned_qty": 36,
      "return_rate_orders": 4.2,
      "return_value": 5120.10,
      "refund_processed_pct": 78.6
   },
   "status_breakdown": [
      {"status": "pending", "count": 12},
      {"status": "in_transit", "count": 9},
      {"status": "delivered", "count": 4},
      {"status": "completed", "count": 3}
   ],
   "top_reasons": [
      {"reason": "DONT_LIKE_IT", "count": 11}
   ]
}
```

#### GET /api/stats/logistics

Przeznaczenie:
1. lead time i SLA operacyjne.

```json
{
   "lead_times_hours": {
      "order_to_label_p50": 2.1,
      "order_to_label_p90": 9.8,
      "label_to_delivered_p50": 28.0
   },
   "sla": {
      "within_24h_label_pct": 93.2,
      "late_orders_count": 22
   },
   "error_counts": {
      "blad_druku": 7,
      "problem_z_dostawa": 4
   }
}
```

#### GET /api/stats/products

Przeznaczenie:
1. top produkty, marza, wolnoobrot.

```json
{
   "top_by_revenue": [
      {"product": "Front Line L czarne", "qty": 84, "revenue": 17388.00, "profit": 5320.20}
   ],
   "top_by_margin_pct": [
      {"product": "Adventure M", "margin_pct": 38.4}
   ],
   "slow_movers": [
      {"product": "Premium XL rozowe", "stock": 21, "sold_30d": 1}
   ],
   "stock_risk": [
      {"product": "Front Line L", "days_to_stockout": 4.2}
   ]
}
```

#### GET /api/stats/competition

Przeznaczenie:
1. pozycja cenowa i benchmark konkurencji.

```json
{
   "summary": {
      "offers_monitored": 312,
      "share_cheapest_pct": 41.7,
      "avg_price_gap": 1.83,
      "offers_above_competitor": 129
   },
   "distribution": [
      {"bucket": "<=0.00", "count": 130},
      {"bucket": "0.01-2.00", "count": 102},
      {"bucket": ">2.00", "count": 80}
   ]
}
```

### 16.4 Kontrakty bledu

```json
{
   "ok": false,
   "generated_at": "2026-04-01T12:00:00Z",
   "data": null,
   "errors": [
      {
         "code": "ALLEGRO_TOKEN_INVALID",
         "message": "Brak waznego tokenu Allegro",
         "source": "allegro_api.billing"
      }
   ]
}
```

## 17. Plan sprintow (checklista wykonawcza)

Status aktualizacji: 2026-04-01

### Sprint 1: Fundament i endpoint overview

1. [x] Utworzyc blueprint `stats` i routing.
2. [x] Dodac warstwe DTO dla filtrow i walidacji.
3. [x] Zaimplementowac `GET /api/stats/overview`.
4. [x] Dodac cache dla endpointow fast.
5. [x] Dodac testy jednostkowe definicji KPI.
6. [x] Dodac testy integracyjne API overview.

### Sprint 2: Sales + Profit + Allegro costs

1. [x] Zaimplementowac `GET /api/stats/sales`.
2. [x] Zaimplementowac `GET /api/stats/profit`.
3. [x] Zaimplementowac `GET /api/stats/allegro-costs`.
4. [x] Dodac mapowanie typow billingowych i fallbacki.
5. [x] Dodac porownania MoM/WoW.
6. [x] Dodac testy zgodnosci revenue vs billing.

### Sprint 3: Returns + Logistics

1. [x] Zaimplementowac `GET /api/stats/returns`.
2. [x] Zaimplementowac `GET /api/stats/logistics`.
3. [x] Dodac agregacje lead time z `order_status_logs`.
4. [x] Dodac metryki refund_processed i skutecznosci zwrotow.
5. [x] Dodac alerty operacyjne i progi.

### Sprint 4: Products + Competition

1. [x] Zaimplementowac `GET /api/stats/products`.
2. [x] Zaimplementowac `GET /api/stats/competition`.
3. [x] Polaczyc dane `price_report_items` i `allegro_price_history`.
4. [x] Dodac rekomendacje repricingowe.
5. [x] Dodac eksport CSV/XLSX i testy eksportu.

### Sprint 5: Frontend i hardening

1. [x] Zbudowac nowa zakladke menu i layout dashboardu.
2. [x] Dodac komponenty wykresow i drill-down.
3. [x] Dodac lazy loading sekcji heavy.
4. [x] Dodac telemetrie czasu odpowiedzi i cache hit ratio.
5. [x] Testy wydajnosci i finalne strojenie zapytan.

### Sprint 6: Kompletacja delty MoM/WoW + funnel + waterfall

1. [x] Zaimplementowac realne wartosci MoM i WoW w `GET /api/stats/overview` (poprzedni okres = analogiczny odcinek czasu przed date_from).
2. [x] Dodac `funnel` i `error_counts` do `GET /api/stats/logistics` (ustrukturyzowane etapy i bledy etykiet z OrderStatusLog).
3. [x] Dodac wykres waterfall (Przychod -> koszty -> zysk netto) do dashboardu na podstawie danych z `GET /api/stats/profit`.
4. [x] Testy jednostkowe: MoM w overview nie zwraca None przy danych historycznych, funnel w logistics, waterfall w dashboardzie renderuje sie bez bledow.
5. [x] Zaktualizowac dokumentacje i zbudowac kontenery po wdrozeniu.

## 18. Allegro: co mamy vs co jeszcze mozemy wziac do statystyk

### 18.1 Dane Allegro juz wykorzystywane

1. Checkout forms i fulfillment statusy (sprzedaz, statusy realizacji).
2. Billing entries per order i per okres (prowizje, promo, shipping, listing).
3. Ads NSP (koszt dzienny kampanii).
4. Returns + statusy i paczki zwrotne.
5. Tracking przesylek i mapowanie przewoznikow.
6. Promotions i terminy odnowien.
7. Offer details (cena, status publikacji).

### 18.2 Dodatkowe dane, ktore mozemy pozyskac od razu (niskim kosztem)

1. Pelna tabela `billing_types` z opisami i wersjonowaniem mapowania.
    1. Cel: dokladniejsze raporty kosztowe bez recznego utrzymywania slownika.
2. Surowe eventy zamowien (`order/events`) do analizy czasu przejsc miedzy etapami.
    1. Cel: pelny funnel i wykrywanie opoznien.
3. Metryki jakosci obslugi klienta z messaging/issues.
    1. Np. liczba watkow, SLA pierwszej odpowiedzi, backlog dyskusji.
4. Invoice upload status i pokrycie faktur po stronie Allegro.
    1. Cel: KPI zgodnosci dokumentowej.
5. Szczegoly create-commands/cancel-commands przesylek z Shipment Management.
    1. Cel: statystyki bledow etykiet per metoda dostawy.

### 18.3 Dodatkowe dane, ktore wymagaja rozszerzenia integracji (sredni koszt)

1. Granularny koszt reklam po kampanii/ofercie (jesli dostepny w API konta i billing).
    1. Cel: ROAS i koszt reklamy na produkt.
2. Dzienna historia publikacji/zmian ofert (status, cena, zmiany parametrow).
    1. Cel: korelacja zmian oferty z wynikiem sprzedazy.
3. Dane refundowe per etap i czas zwrotu pieniedzy.
    1. Cel: KPI czasu rozliczenia zwrotu.
4. Rozszerzony tracking delivery (gdy API zwraca wiecej statusow i timestampow).
    1. Cel: SLA per przewoznik i metoda.

### 18.4 Dane, ktore warto potwierdzic na etapie implementacji z dokumentacja Allegro

1. Zakres danych statystycznych per oferta (viewy, konwersja, CTR) i limity pobran.
2. Rozdzielczosc danych reklam (konto/kampania/oferta/slowo) i retencja historyczna.
3. Ograniczenia rate limit dla endpointow finansowych i trackingowych.
4. Dokladny model statusow zwrotu/refund i ich przejsc.

## 19. Priorytet nowych danych Allegro do wdrozenia

1. Priorytet A (wdrozyc w MVP+):
    1. slownik billing_types,
    2. surowe order/events do funnelu,
    3. bledy shipment create/cancel do KPI etykiet.
2. Priorytet B:
    1. KPI obslugi klienta z messaging/issues,
    2. KPI pokrycia faktur.
3. Priorytet C:
    1. rozszerzone dane reklam i offer analytics po potwierdzeniu dostepnosci.

## 21. Sprint 7: Priorytet A - billing types (start)

1. [x] Dodac trwala tabele `allegro_billing_types` z wersjonowaniem mapowania (`mapping_version`).
2. [x] Dodac synchronizacje slownika billing types podczas `GET /api/stats/allegro-costs`.
3. [x] Dodac test API potwierdzajacy zapis slownika do DB.
4. [x] Dodac UI/raport mapowania kategorii billingowych (mapping_category) i panel recznej korekty.
5. [x] Dodac job okresowej synchronizacji billing types niezalezny od wejscia na dashboard.

## 20. Definicja sukcesu modulu Statystyki

1. Wlasciciel biznesowy dostaje 1 ekran z realnym wynikiem finansowym i delta okresowa.
2. Kazdy KPI ma drill-down do zamowien/produktow/ofert.
3. Koszty Allegro i Ads sa rozliczalne i porownywalne do przychodu.
4. Zwroty, logistyka i konkurencja sa widoczne jako czynniki wyniku.
5. Raporty sa stabilne, powtarzalne i nadaja sie do podejmowania decyzji cenowych i operacyjnych.
