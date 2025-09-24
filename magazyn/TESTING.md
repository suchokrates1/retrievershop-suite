# Plan testów Allegro scraper

## Testy automatyczne
- `pytest magazyn/tests/test_allegro_scraper_driver.py`
- `pytest magazyn/tests/test_allegro_price_monitor.py`
- `pytest magazyn/tests/test_allegro_price_check.py`

## Testy manualne
1. Uruchom skrypt `fetch_competitors` dla przykładowej oferty z włączonym logowaniem i zweryfikuj, że klikany jest odnośnik „Najtańsze”.
2. Obserwuj przewijanie do sekcji `#inne-oferty-produktu` oraz pojawienie się arkusza `opbox-sheet` z kartami ofert.
3. Zweryfikuj parsowanie ceny i sprzedawcy dla kilku różnych kart ofert, w tym z alternatywnymi atrybutami (aria-label, data-role).
4. Sprawdź reakcję na banery cookies/overlaye poprzez ręczne wywołanie trybu prywatnego oraz wersji z iframe.
5. Potwierdź wykrywanie ekranów anty-botowych poprzez zasymulowanie blokady i sprawdzenie komunikatu w logach.
