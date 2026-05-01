# Plan migracji fasad i importow

Stan na teraz: plan jest wykonany w glownym zakresie. Najwazniejszy hard-cut starych importow do `magazyn.orders`, `magazyn.price_reports`, `magazyn.print_agent` oraz zbiorczego `magazyn.models` zostal wdrozony w kodzie produkcyjnym i utwardzony testem architektonicznym. Po rundzie 2026-05-01 wewnetrzne uzycia agenta drukowania ida przez jawny runtime `magazyn.services.print_agent_runtime`, a `magazyn.models.__init__` jest pustym markerem pakietu bez eksportow agregujacych.

## Postep rundy 2026-05-01

- [x] Dodano jawny runtime `magazyn.services.print_agent_runtime` dla singletona agenta drukowania.
- [x] Przepieto produkcyjne importy `agent` ze starej fasady `magazyn.print_agent` na `magazyn.services.print_agent_runtime`.
- [x] Przepieto testy agenta z `import magazyn.print_agent as pa` na jawny runtime serwisowy.
- [x] Zostawiono `magazyn.print_agent` tylko jako cienki shim kompatybilnosciowy `agent/logger`.
- [x] Wzmocniono guard architektoniczny tak, aby blokowal dowolny powrot importow z `magazyn.print_agent` w kodzie repo.
- [x] Zamieniono `magazyn.models.__init__` w pusty marker pakietu bez eksportow `Base` i `import_all_models`.
- [x] Dodano guard pilnujacy, zeby `magazyn.models.__init__` nie zaczal ponownie eksportowac agregatu modeli.
- [x] Wydzielono akcje zwrotow z `magazyn.orders` do `magazyn.services.order_return_actions`.
- [x] Zbito `magazyn.orders` ponizej budzetu root-modulu: 342 linie przy limicie 450.
- [x] Walidacja punktowa zmienionych testow: 30 passed.
- [x] Backend bez wizualnych snapshotow: 598 passed, 32 skipped, 1 xfailed.
- [x] E2E bez snapshotow wizualnych: `test_mobile_menu.py` 10 passed.
- [x] `ruff check magazyn scripts migrations`, `compileall magazyn` oraz `git diff --check` przeszly dla zakresu aplikacji.
- [ ] Opcjonalnie: zdecydowac, czy endpointy HTTP `recheck_item` i `change_price` w `price_reports.py` maja zostac przemianowane.
- [ ] Opcjonalnie: osobnym etapem przejrzec pozostale fasady kompatybilnosci, przede wszystkim `magazyn.returns`.

Uwagi walidacyjne:

- Pelne `ruff check .` nadal blokuje niezalezny katalog `.github/prompts/ui-ux-pro-max/scripts`, ktory ma istniejace bledy F401/F541/F841 poza zakresem tej migracji.
- Pelne `pytest` z wizualnymi snapshotami blokuje `magazyn/tests/e2e/test_visual_snapshots.py` przez roznice obrazow po przekierowaniu na `/login`; niewizualne E2E przechodzi.

## Status ogolny

Podsumowanie biezace:

| Obszar | Status | Ocena |
| --- | --- | --- |
| Hard-cut importow `magazyn.orders.*` | wykonane | Stare funkcje nie sa juz importowane, a `orders.py` korzysta bezposrednio z serwisow. |
| Hard-cut importow `magazyn.price_reports.*` | wykonane w praktyce | Kod nie importuje juz starego API, ale w module route pozostaly endpointy HTTP `recheck_item` i `change_price`. |
| Hard-cut importow `magazyn.print_agent.*` | wykonane | Wewnetrzne importy ida przez `magazyn.services.print_agent_runtime`; `magazyn.print_agent` zostal tylko jako shim kompatybilnosciowy. |
| Migracja z `magazyn.models` na jawne podmoduly | wykonane | Importy ida przez `magazyn.models.<domena>` lub `.models.<domena>`, a `magazyn.models.__init__` nie eksportuje juz agregatu. |
| Przepiecie testow blokujacych hard-cut | wykonane | Testy nie korzystaja juz z bootstrapu `magazyn.print_agent as pa`. |
| Twarda blokada regresji | wykonane i rozszerzone | Guard blokuje powrot do starych importow, wewnetrzne uzycie `magazyn.print_agent` oraz eksporty z `magazyn.models.__init__`. |

Bilans roboczy dla tego planu:

- wykonane: 6 glownych obszarow,
- wykonane czesciowo lub wymagajace doprecyzowania: 0 obszarow krytycznych,
- krytyczne blokery: 0.

## Co zostalo juz zrobione

### 1. `magazyn.orders` przestal byc API serwisowym

Status: wykonane.

Wnioski:

- Nie ma juz technicznych importow `sync_order_from_data`, `add_order_status` ani `_dispatch_status_email` ze starej fasady `magazyn.orders`.
- Sam `magazyn/orders.py` pracuje na bezposrednich zaleznosciach serwisowych.
- Produkcyjny skrypt `scripts/sync_allegro_orders.py` importuje `add_order_status` z `magazyn.services.order_status` oraz `sync_order_from_data` z `magazyn.services.order_sync`.

Znaczenie:

- Cel planu dla zamowien zostal dowieziony: route module nie jest juz traktowany jako miejsce logiki domenowej.

### 2. `magazyn.price_reports` przestal byc API mutacji raportu

Status: wykonane w praktyce.

Wnioski:

- Nie znaleziono importow starych symboli `magazyn.price_reports.recheck_item` ani `magazyn.price_reports.change_price`.
- Endpointy w `magazyn/price_reports.py` deleguja bezposrednio do `magazyn.services.price_report_mutation`.
- Test `magazyn/tests/test_price_scraping.py` sprawdza juz bezposrednio `change_report_item_price` z serwisu.

Niuans:

- Funkcje `recheck_item` i `change_price` nadal istnieja w module route jako endpointy HTTP. To nie jest juz stare API serwisowe, ale nazwy pozostaly i warto swiadomie zdecydowac, czy maja zostac jako warstwa HTTP, czy chcesz je dodatkowo uproscic lub przemianowac.

### 3. `magazyn.print_agent` zostal sciety do bootstrapu runtime

Status: wykonane.

Wnioski:

- `magazyn/print_agent.py` eksportuje tylko `agent` oraz `logger` jako shim kompatybilnosciowy.
- Wewnetrzny runtime singletona znajduje sie w `magazyn.services.print_agent_runtime`.
- Nie ma tam klas, funkcji pomocniczych, `__getattr__` ani re-eksportu dawnych narzedzi.
- Stare symbole typu `AgentConfig`, `calculate_cod_amount`, `start_agent_thread`, `stop_agent_thread`, `settings`, `LabelAgent`, a takze sam import starej fasady w repo, sa blokowane przez guard architektoniczny.
- `magazyn/__init__.py` nie robi juz lazy-fasady dla agenta drukowania.
- `magazyn/agent/migrate.py` korzysta bezposrednio z `magazyn.label_agent.LabelAgent` i `magazyn.services.print_agent_config.AgentConfig`.

Efekt rundy 2026-05-01:

- Testy `magazyn/tests/test_agent_thread.py`, `magazyn/tests/test_logging.py`, `magazyn/tests/test_weekly_reports.py`, `magazyn/tests/test_db_config.py`, `magazyn/tests/test_courier_code.py` i `magazyn/tests/test_utils.py` korzystaja juz z `magazyn.services.print_agent_runtime`.
- Stary modul `magazyn.print_agent` zostal zdegradowany do kompatybilnosci z zewnetrznymi importami, nie do wewnetrznego API aplikacji.

### 4. Zbiorczy agregat `magazyn.models` przestal byc uzywany jako publiczne API

Status: wykonane.

Wnioski:

- W kodzie produkcyjnym i skryptach importy ida jawnie przez podmoduly, np. `magazyn.models.orders`, `magazyn.models.products`, `magazyn.models.users`, `magazyn.models.base`, `magazyn.models.registry`.
- `migrations/env.py` importuje `Base` z `magazyn.models.base`, a nie ze zbiorczego agregatu.
- `magazyn/models/__init__.py` zostal zredukowany do pustego markera pakietu bez eksportow agregujacych.

Decyzja rundy 2026-05-01:

- Plik zostaje jako marker pakietu, ale nie pelni juz roli API.
- Guard architektoniczny pilnuje, zeby nie wrocily importy i eksporty agregujace modele.

### 5. Guard architektury zostal domkniety

Status: wykonane.

Najwazniejsze efekty:

- `magazyn/tests/test_architecture_imports.py` blokuje stare importy z:
  - `magazyn.models`
  - `magazyn.orders`
  - `magazyn.price_reports`
  - `magazyn.print_agent`
- Guard pilnuje, zeby `magazyn.print_agent` pozostawal cienkim bootstrapem.
- Guard pilnuje, zeby kod repo nie importowal juz `magazyn.print_agent` jako wewnetrznego runtime.
- Guard pilnuje, zeby `magazyn.models.__init__` pozostal pustym markerem bez eksportow.
- `LEGACY_ROOT_MODULE_BUDGETS = {}` potwierdza, ze wyjatki rozmiarowe dla root-modulow zostaly zdjete.

Znaczenie:

- Najbardziej ryzykowna czesc planu, czyli powrot starych importow przy kolejnych zmianach, jest juz aktywnie blokowana.

## Ocena planu na dzis

### Punkt 1. Hard-cut dla `magazyn.orders.*`

Status: wykonane.

### Punkt 2. Hard-cut dla `magazyn.price_reports.*`

Status: wykonane funkcjonalnie.

Komentarz:

- Importy i call-site'y starego API zniknely.
- Zostala tylko cienka warstwa endpointow HTTP.

### Punkt 3. Hard-cut dla `magazyn.print_agent.*`

Status: wykonane.

Komentarz:

- Wewnetrzne uzycia przeszly na `magazyn.services.print_agent_runtime`.
- `magazyn.print_agent` zostal tylko jako shim kompatybilnosciowy i jest blokowany jako zaleznosc wewnetrzna.

### Punkt 4. Jawne importy modeli w kodzie produkcyjnym

Status: wykonane.

Komentarz:

- Named modules z planu pracuja na importach `magazyn.models.<domena>` albo `.models.<domena>`.

### Punkt 5. Przepiecie testow przed hard-cutem

Status: wykonane.

Komentarz:

- Testy blokujace stare symbole i testy agenta korzystaja juz z nowych modulow serwisowych.

### Punkt 6. Blokada regresji

Status: wykonane.

Wniosek dla calego planu na dzis:

- Plan na dzis jest w praktyce dowieziony.
- Obszary krytyczne sa domkniete. Zostaly tylko opcjonalne porzadki nazw endpointow i przeglad innych fasad kompatybilnosci.

## Ocena planu na jutro

### Punkt 1. Dopiac polityke publicznego API dla agenta

Status: wykonane.

Stan:

- Jawny punkt wejscia to `magazyn.services.print_agent_runtime`.
- `magazyn.print_agent` zostaje tylko shimem kompatybilnosciowym i nie jest uzywany wewnatrz repo.

### Punkt 2. Domknac los `magazyn.models.__init__`

Status: wykonane.

Stan:

- Uzycie agregatu zostalo wyciete.
- Plik zostal jako pusty marker pakietu bez eksportow.

### Punkt 3. Utrwalic hard-cut przez dodatkowe guardy

Status: wykonane.

Stan:

- Guard blokuje legacy importy, import samego `magazyn.print_agent` w kodzie repo oraz eksporty agregatu `magazyn.models`.

### Punkt 4. Cleanup po migracji

Status: otwarte tylko opcjonalne porzadki, brak blokera.

Stan:

- Kod jest juz po stronie nowej architektury.
- Zostaly nazwy endpointow HTTP i ewentualny przeglad innych fasad kompatybilnosci poza tym planem.

## Mapa docelowa importow

Docelowy kierunek jest juz w praktyce wdrozony:

| Stara sciezka | Docelowa sciezka | Stan |
| --- | --- | --- |
| `magazyn.orders.sync_order_from_data` | `magazyn.services.order_sync.sync_order_from_data` | wykonane |
| `magazyn.orders.add_order_status` | `magazyn.services.order_status.add_order_status` | wykonane |
| `magazyn.price_reports.change_price` | `magazyn.services.price_report_mutation.change_report_item_price` | wykonane |
| `magazyn.price_reports.recheck_item` | `magazyn.services.price_report_mutation.recheck_report_item` | wykonane |
| `magazyn.print_agent.AgentConfig` | `magazyn.services.print_agent_config.AgentConfig` | wykonane |
| `magazyn.print_agent.calculate_cod_amount` | `magazyn.services.print_agent_config.calculate_cod_amount` | wykonane |
| `magazyn.print_agent.agent` | `magazyn.services.print_agent_runtime.agent` | wykonane wewnatrz repo |
| `magazyn.print_agent.logger` | `magazyn.services.print_agent_runtime.logger` | wykonane wewnatrz repo |
| `magazyn.models` | `magazyn.models.<domena>` albo `.models.<domena>` | wykonane w produkcji |

## Kolejnosc dalszych prac

Najrozsadniejsza kolejnosc od tego miejsca:

1. [x] Podjac jawna decyzje, czy `magazyn.print_agent` zostaje jako oficjalny bootstrap `agent` i `logger`.
2. [x] Jezeli nie, przepiac `test_agent_thread.py`, `test_logging.py` i `test_weekly_reports.py` na nowy, jawny punkt wejscia.
3. [x] Zdecydowac, czy `magazyn/models/__init__.py` zostaje jako minimalny bootstrap dla infrastruktury, czy ma zostac usuniety po dodatkowej walidacji.
4. [x] Dopisac kolejny guard zabraniajacy importu samego `magazyn.print_agent` w kodzie repo.
5. [ ] Opcjonalnie doprecyzowac, czy endpointowe funkcje `recheck_item` i `change_price` zostawiaja stare nazwy jako element HTTP API, czy chcesz je nazwac bardziej jednoznacznie.

## Definition of Done - stan faktyczny

Ocena wobec definicji ukonczenia:

| Kryterium | Status | Komentarz |
| --- | --- | --- |
| `rg` nie znajduje starych importow z `magazyn.orders` | spelnione | Potwierdzone analizą i guardem. |
| `rg` nie znajduje starych importow z `magazyn.price_reports` | spelnione | Potwierdzone analizą i guardem. |
| `rg` nie znajduje legacy symboli z `magazyn.print_agent` | spelnione | Wewnetrzne uzycia `agent/logger` tez przeszly na `magazyn.services.print_agent_runtime`. |
| Kod produkcyjny nie korzysta ze zbiorczego `magazyn.models` | spelnione | Importy ida przez podmoduly, a `magazyn.models.__init__` jest pustym markerem. |
| `orders.py`, `price_reports.py`, `print_agent.py` nie sa juz API biznesowym | spelnione w praktyce | Pozostaly role HTTP/bootstrap, nie warstwa serwisowa. |
| Guard blokuje regresje | spelnione | Obejmuje legacy importy, import `magazyn.print_agent` i pusty marker `magazyn.models.__init__`. |
| Root-moduly mieszcza sie w budzecie 450 linii | spelnione | `magazyn.orders` po wydzieleniu akcji zwrotow ma 342 linie. |

## Otwarte punkty

To nie sa blokery dla obecnego stanu architektury, ale sensowne follow-upy:

1. Czy endpointy `recheck_item` i `change_price` maja zostac przemianowane, mimo ze sa juz tylko warstwa HTTP.
2. Czy chcesz ruszac pozostale fasady kompatybilnosci poza tym planem, np. `magazyn.returns`, ktory nadal jest opisany jako warstwa kompatybilnosci dla starszych importow.

## Rekomendacja

Rekomendacja operacyjna po rundzie 2026-05-01: uznac migracje fasad i importow za domknieta w glownym zakresie. Nastepne prace prowadzic jako osobne, mniejsze etapy: nazewnictwo endpointow HTTP oraz ewentualny przeglad innych fasad kompatybilnosci.