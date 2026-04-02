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

---

## 9. Audyt wykonania planu (2026-04-02)

### Co zostalo zrealizowane
| Punkt planu | Status |
|---|---|
| A1. Nawigacja - dopasowanie CSS do HTML | DONE - martwe selektory (.navbar-nav, #mobileMenuBtn) usuniete |
| A1. Backdrop + zamykanie po tapie | DONE - Alpine.js x-data + .mobile-menu-backdrop |
| A1. Blokada scrolla body | DONE - x-effect + body.menu-open { overflow: hidden } |
| A1. Mniejsze logo na mobile | DONE - h-[48px] md:h-[140px] |
| A2. Usuniecie reguly :has(> table) | DONE - regula nie istnieje |
| A2. Standard overflow-x-auto | CZESCIOWO - regula w CSS jest ale nie wszystkie tabele ja uzywaja |
| A3. Spacing mobile | CZESCIOWO - padding-top OK, ale hardcoded |
| B1-B3. Widoki P0 | 30-50% - karty responsywne, ale formularze i tabele nie |
| C. Widoki P1/P2 | NIE ROZPOCZETE |

### Wykryte przyczyny braku responsywnosci (ROOT CAUSES)

**RC1 (krytyczny): Globalna regula `label, input, button { margin: 5px 0; padding: 8px }` (styles.css:68)**
- Nadpisuje padding/margin na KAZDYM przycisku, inpucie i labelu
- DaisyUI klasy btn-sm, input-bordered, p-2 sa ignorowane bo regula laduje sie po Tailwind CDN
- Powoduje ze elementy sa wieksze niz powinny i nie mieszcza sie na mobile

**RC2 (wazny): Brak flex-wrap na formularzach filtrow**
- orders_list.html: formularz wyszukiwania `flex gap-2` bez `flex-wrap`
- orders_list.html: date inputs `w-[130px]` bez fallbacku mobile
- stats_dashboard.html: 6 filtrow w flex-wrap ale kazdy bez `w-full md:w-auto`
- items.html: formularz + przyciski w jednej linii

**RC3 (wazny): Tabele bez overflow-x-auto lub bez min-width**
- items.html: 15+ kolumn rozmiarow bez min-width - kolumny kolapsuja do 0px
- home.html: tabela dostaw bez overflow-x-auto na glownym kontenerze
- stats_dashboard.html: tabele logistyki OK (maja overflow-x-auto)

**RC4 (sredni): Hardcoded padding-top 210px/72px**
- Kruche rozwiazanie - zmiana navbara wymaga recznej aktualizacji CSS
- Mozliwe ze padding nie odpowiada faktycznej wysokosci navbara

**RC5 (niski): Brak spolnego wzorca container na stronach full_width**
- orders_list.html, items.html ustawiaja full_width=True ale dodaja wlasny container

## 10. Plan poprawek (wdrozenie natychmiastowe)

### FIX-1: Usuniecie globalnej reguly label/input/button (RC1)
- Plik: `magazyn/static/styles.css` linia 68
- Akcja: usunac `label, input, button { margin: 5px 0; padding: 8px }`
- Zastapic regula waskoscope `.login-form label, .login-form input, .login-form button` jesli login potrzebuje paddingu
- Wplyw: natychmiastowa poprawa rozmiarow przyciskow i inputow w calej aplikacji

### FIX-2: flex-wrap na formularzach filtrow (RC2)
- `orders_list.html:20` - dodac `flex-wrap` do formularza wyszukiwania
- `orders_list.html:70` - date inputs: `w-full sm:w-[130px]` zamiast `w-[130px]`
- `orders_list.html:55` - status filter `.join`: dodac wrapper z `overflow-x-auto`
- `items.html:11` - dodac `flex-wrap` do kontenera formularza + przyciskow
- `stats_dashboard.html:107` - filtry: `w-full sm:w-auto` na kazdym input/select

### FIX-3: Tabele overflow + min-width (RC3)
- `items.html:55` - dodac `min-w-[800px]` na tabeli z rozmiarami
- Weryfikacja ze wszystkie tabele P0 sa w `.overflow-x-auto`

### FIX-4: orders_list date form mobile (RC2)
- Formularz dat: `flex-col sm:flex-row` zamiast `flex flex-wrap`
- Labele "Od:"/"Do:" i inputy w jednej linii na desktop, stackowane na mobile

### FIX-5: stats_dashboard filtry mobile (RC2)
- Filtry: kazdy input/select dostaje `w-full sm:w-auto`
- Przycisk "Odswierz" na pelna szerokosc na mobile
