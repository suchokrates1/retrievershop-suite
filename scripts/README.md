# Skrypty pomocnicze

Ten katalog zawiera skrypty używane do analizy, debugowania i napraw danych.

## Struktura

### `analysis/`
Skrypty do analizy i napraw danych:

**Analiza zamówień i statusów:**
- `check_order_history.py` - wyświetla historię statusów zamówienia
- `check_order_status.py` - sprawdza statusy zamówień
- `check_deliveries.py` - sprawdza dostawy

**Analiza i naprawa kodów EAN:**
- `check_ean_db.py` - sprawdza bazę kodów EAN
- `check_ean_match.py` - sprawdza dopasowania EAN
- `check_missing_eans.py` - znajduje brakujące EAN
- `analyze_missing_eans.py` - analizuje brakujące EAN
- `fix_eans.py` - naprawia błędne EAN
- `fix_ean_links.py` - naprawia linki do EAN
- `fill_missing_barcodes.py` - uzupełnia brakujące kody kreskowe
- `fill_missing_barcodes_v2.py` - wersja 2 uzupełniania kodów
- `verify_ean_database.py` - weryfikuje bazę EAN
- `update_batch_eans.py` - aktualizuje EAN w partiach

**Analiza produktów:**
- `analyze_products.py` - analizuje produkty
- `check_products.py` - sprawdza produkty
- `list_products.py` - listuje produkty
- `list_products_details.py` - szczegółowa lista produktów
- `check_quantities.py` - sprawdza ilości
- `check_unmatched.py` - sprawdza niedopasowane produkty
- `search_by_names.py` - wyszukuje po nazwach

**Analiza faktur:**
- `analyze_invoice.py` - analizuje faktury
- `read_invoice.py` - odczytuje faktury
- `check_invoice_eans.py` - sprawdza EAN z faktur
- `compare_invoice.py` - porównuje faktury
- `compare_delivery.py` - porównuje dostawy

**Analiza partii (batches):**
- `check_batches.py` - sprawdza partie
- `fix_batch_85.py` - naprawia konkretną partię 85

**Skrypty specyficzne:**
- `check_pas_amortyzator.py` - sprawdza konkretny produkt
- `fix_pas_amortyzator.py` - naprawia konkretny produkt
- `check_product_41.py` - sprawdza produkt 41
- `fix_product_41.py` - naprawia produkt 41
- `list_truelove.py` - lista produktów TrueLove
- `fix_invalid_eans.py` - naprawia nieprawidłowe EAN

**Testy i narzędzia:**
- `test_scan_all.py` - test skanowania
- `test_update_return.py` - test aktualizacji zwrotów
- `create_scraper_table.py` - tworzy tabelę scrapera

### `archive/`
Archiwalne skrypty już nieużywane

### `debug/`
Skrypty debugowe (puste - możesz dodać tu skrypty tymczasowe)

## Użycie

Wszystkie skrypty powinny być uruchamiane z głównego katalogu repozytorium:

```bash
python scripts/analysis/check_order_history.py
```

lub wewnątrz kontenera Docker:

```bash
docker exec retrievershop-suite-magazyn_app-1 python3 scripts/analysis/check_order_history.py
```
