# Plan wdrożenia pełnej responsywności UI

## 1. Cel i zakres
Celem jest zapewnienie poprawnego działania wszystkich widoków aplikacji na:
- telefonie: 360x800, 390x844, 412x915
- tablecie: 768x1024, 820x1180
- desktopie kontrolnym: >=1280

Zakres obejmuje wszystkie szablony w `magazyn/templates` (47 widoków) oraz style globalne `magazyn/static/styles.css`.

## 2. Najważniejsze problemy wykryte w audycie
1. Globalne wyłączanie poziomego scrolla tabel:
- reguła `.overflow-x-auto:has(> table) { overflow-x: visible; }`
- skutek: tabele nie przewijają się poziomo na mobile i rozpychają layout

2. Regresja mobile menu po zmianie navbara:
- CSS nadal zawiera selektory z poprzedniej struktury (`.navbar-nav`, `#mobileMenuBtn`, `#mobileMenu .custom-btn`), które nie pasują do aktualnego HTML
- brak backdropu i blokady scrolla strony przy otwartym menu
- duże elementy naglowka (`logo h-[140px]`, `text-2xl`) ograniczają miejsce na przycisk hamburgera

3. Niespójność etykiet w statystykach:
- część etykiet funnelu jest mapowana do PL, a część nadal renderowana z surowych statusow (`stage.status`, `row.transition.replace(...)`)

4. Regresja karty KPI w statystykach:
- konfiguracja poczatkowa zawiera 4 karty (w tym `Zysk netto`), ale `updateCards()` nadpisuje je do 3 kart

5. Brak wspolnego standardu responsywnosci dla tabel, formularzy i kart:
- wiele widokow ma indywidualne rozwiazania, bez jednolitego komponentu i bez stalego zestawu breakpointow

## 3. Priorytety widokow
## P0 (krytyczne, naprawa w pierwszym wdrozeniu)
- `base.html` (menu, navbar, spacing globalny)
- `stats_dashboard.html` (duza gestosc danych i tabel)
- `home.html` (dashboard operacyjny)
- `orders_list.html`, `order_detail.html`
- `items.html`, `product_detail.html`

## P1 (wysoki)
- `allegro/offers_and_prices.html`, `allegro/offers.html`
- `sales_list.html`, `sales.html`
- `history.html`, `scan_logs.html`, `review_invoice.html`
- `price_reports/*`

## P2 (sredni)
- formularze: `add_order.html`, `add_item.html`, `add_delivery.html`, `edit_item.html`, `import_*`
- `settings.html`, `sales_settings.html`
- strony techniczne/testowe

## 4. Strategia wdrozenia (iteracyjna)
## Etap A - fundamenty globalne (1 sprint)
1. Uporzadkowanie nawigacji mobilnej:
- dopasowanie CSS do aktualnej struktury HTML
- dodanie backdropu + zamykanie po tapie poza panelem
- blokada scrolla body przy otwartym menu
- poprawa ergonomii naglowka na <768px (mniejszy logo, krotszy/ukryty tytul)

2. Standard tabel mobilnych:
- usuniecie globalnej reguly wylaczajacej `overflow-x`
- wprowadzenie jednego wzorca `table-scroll` z:
  - `overflow-x: auto`
  - `-webkit-overflow-scrolling: touch`
  - minimalna szerokosc tabel tylko tam, gdzie konieczna

3. System spacingu i typografii mobilnej:
- zmniejszenie globalnych offsetow nav dla mobile
- standaryzacja naglowkow (`text-xl` na mobile, `text-2xl+` od md)

## Etap B - widoki krytyczne P0 (1 sprint)
1. `stats_dashboard.html`:
- ujednolicenie etykiet statusow i przejsc przez jedna funkcje mapujaca
- przywrocenie/brakujaca karta `Zysk netto`
- kompaktowe siatki kart 2->1 na waskich ekranach
- tabele: przewijanie + skrocone kolumny + `title` dla pelnych wartosci

2. `home.html`:
- sekcja miesieczna `grid-cols-4` -> responsywny podzial (2/2 lub 1/1)
- przeglad wszystkich tabel i kart pod katem overflow

3. listy i detale zamowien/produktow:
- priorytet czytelnosci tabel i formularzy akcji
- sticky akcje krytyczne na mobile (jesli potrzebne)

## Etap C - widoki P1 i P2 (1 sprint)
1. Przejscie przez wszystkie pozostale widoki wg checklisty.
2. Eliminacja lokalnych hackow CSS na rzecz wspolnych klas utility.
3. Finalne porzadki i usuniecie martwych selectorow.

## 5. Checklista testowa (Definition of Done)
Kazdy widok uznajemy za gotowy, gdy:
1. Brak poziomego overflow calej strony na 360px.
2. Tabele maja kontrolowany poziomy scroll, bez ucinania kluczowych danych.
3. Mobile menu jest w pelni obslugiwalne:
- otwarcie/zamkniecie
- zamkniecie po kliknieciu poza panelem
- zamkniecie po wyborze pozycji
- brak konfliktu z przewijaniem strony
4. Formularze sa obslugiwalne kciukiem (odstepy, szerokosci, CTA).
5. Brak nachodzenia naglowkow, kart i badge.
6. Brak regresji desktopowej.

## 6. Automatyzacja i kontrola jakosci
1. Dodac testy wizualne Playwright (snapshoty) dla kluczowych widokow P0.
2. Dodac smoke testy E2E dla mobile menu.
3. Dodac linter stylow/konwencji klas dla layoutu (opcjonalnie).

## 7. Plan wdrozenia na produkcje
1. Wdrozenie etapami: A -> B -> C.
2. Po kazdym etapie:
- testy lokalne
- deploy na `minipc`
- weryfikacja `/healthz`
- kontrola logow kontenerow
3. Rollback: standardowy do poprzedniego commita, jesli krytyczna regresja UI.

## 8. Szacowanie
- Etap A: 1-2 dni
- Etap B: 2-3 dni
- Etap C: 2 dni
- Stabilizacja po wdrozeniu: 1 dzien

Lacznie: 6-8 dni roboczych.
