# Allegro Price Scraper - Quick Start

## 🚀 Ultra-prosty start (jeden klik)

1. Pobierz folder `magazyn/scripts/` na dowolny komputer Windows
2. **Kliknij 2x na: `RUN_WORKER.bat`**
3. Gotowe! 🎉

Skrypt **automatycznie**:
- ✅ Sprawdzi i zainstaluje Pythona (jeśli brak)
- ✅ Wykryje Chrome (nawet w niestandardowej lokalizacji)
- ✅ Zainstaluje wszystkie wymagane pakiety
- ✅ Skonfiguruje środowisko
- ✅ Uruchomi scraper

---

## 📋 Co się dzieje pod maską?

### Pierwsze uruchomienie
```
RUN_WORKER.bat
  ↓
Brak Python? → BOOTSTRAP.bat → Instaluje Python 3.12
  ↓
Brak venv? → Tworzy wirtualne środowisko
  ↓
Brak pakietów? → pip install selenium, undetected-chromedriver, etc.
  ↓
Wykrywa Chrome w DOWOLNEJ lokalizacji:
  - C:\Program Files\Google\Chrome\...
  - C:\Program Files (x86)\Google\Chrome\...
  - C:\Users\DOWOLNY_USER\AppData\Local\Google\Chrome\...
  ↓
Uruchamia scraper_worker.py
```

### Kolejne uruchomienia
```
RUN_WORKER.bat
  ↓
Wszystko już jest? → Uruchamia scraper od razu
```

---

## 🛠️ Ręczna instalacja (jeśli potrzebujesz)

### Opcja 1: Full Bootstrap
```batch
BOOTSTRAP.bat
```
Zainstaluje wszystko od zera, nawet Pythona.

### Opcja 2: Tylko setup środowiska
```batch
SETUP.bat
```
Zakłada, że Python już jest zainstalowany.

---

## 🔧 Jak to działa na różnych komputerach?

### Komputer A (np. Twój - C:\Users\sucho\...)
```
RUN_WORKER.bat → Wykrywa Chrome w C:\Users\sucho\AppData\Local\Google\Chrome\...
                 → Działa! ✅
```

### Komputer B (np. C:\Users\jan\...)
```
RUN_WORKER.bat → Wykrywa Chrome w C:\Users\jan\AppData\Local\Google\Chrome\...
                 → Działa! ✅
```

### Komputer C (Chrome w Program Files)
```
RUN_WORKER.bat → Wykrywa Chrome w C:\Program Files\Google\Chrome\...
                 → Działa! ✅
```

### Komputer D (brak Chrome)
```
RUN_WORKER.bat → Nie znajduje Chrome
                 → Wyświetla ostrzeżenie: "Zainstaluj Chrome z google.com/chrome"
                 → Używa domyślnego Chrome (jeśli jest w PATH)
```

---

## 📁 Struktura plików

```
magazyn/scripts/
│
├── RUN_WORKER.bat          ← KLIKNIJ TEN (główny launcher)
├── BOOTSTRAP.bat            ← Pełna instalacja od zera
├── SETUP.bat                ← Szybki setup (zakłada Python)
├── REGISTER_PROTOCOL.bat    ← Rejestruje allegro-scraper:// URL handler
├── LAUNCH_WORKER.bat        ← Uruchamia przez protocol handler
│
├── scraper_worker.py        ← Główny skrypt Pythona
│
├── venv/                    ← Wirtualne środowisko (auto-tworzone)
├── allegro_scraper_profile/ ← Profil Chrome (auto-tworzony)
└── chrome_config.txt        ← Ścieżka do Chrome (auto-wykrywana)
```

---

## 🐛 Troubleshooting

### Problem: "Python not found"
**Rozwiązanie:**
1. Uruchom `BOOTSTRAP.bat` - zainstaluje Pythona automatycznie
2. Lub pobierz ręcznie: https://www.python.org/downloads/
   - Zaznacz "Add Python to PATH" podczas instalacji!

### Problem: "Chrome instance exited"
**Możliwe przyczyny:**
1. Chrome nie jest zainstalowany
   - Pobierz: https://www.google.com/chrome/
2. Chrome jest już otwarty przez inny proces
   - Zamknij wszystkie okna Chrome i spróbuj ponownie
3. Niekompatybilna wersja ChromeDriver
   - Scraper użyje `webdriver-manager` do auto-update

**Rozwiązanie:**
```batch
BOOTSTRAP.bat  ← Przeinstaluje wszystko od zera
```

### Problem: "Session not created"
**Rozwiązanie:**
Scraper automatycznie:
1. Spróbuje `undetected-chromedriver`
2. Jeśli nie działa → Fallback na `selenium` + `webdriver-manager`
3. Jeśli nadal nie działa → Wyświetli szczegóły błędu

### Problem: Scraper nie znajduje ofert
**Sprawdź:**
1. Czy jesteś zalogowany do Allegro w Chrome?
2. Czy https://magazyn.retrievershop.pl jest dostępne?
3. Czy w bazie są oferty z `price > 0`?

---

## ⚙️ Konfiguracja zaawansowana

### Zmiana URL magazynu
Edytuj `RUN_WORKER.bat`:
```batch
python scraper_worker.py --url https://TWOJA_DOMENA.pl
```

### Zmiana batch size / opóźnień
Edytuj `scraper_worker.py`:
```python
BATCH_SIZE = 5  # Ile ofert na raz
MIN_DELAY_BETWEEN_OFFERS = 5  # Min. sekund między ofertami
MAX_DELAY_BETWEEN_OFFERS = 15  # Max. sekund między ofertami
```

### Ręczne ustawienie ścieżki Chrome
Stwórz plik `chrome_config.txt`:
```
CHROME_BINARY=C:\Twoja\Sciezka\Do\chrome.exe
```

---

## 🎯 Jak używać?

### Metoda 1: Bezpośrednie uruchomienie
```batch
RUN_WORKER.bat
```
Scraper działa w tle, sprawdza oferty co 30 sekund.

### Metoda 2: Protocol handler (z UI)
1. Uruchom `REGISTER_PROTOCOL.bat` (jednorazowo)
2. W aplikacji magazyn kliknij "Uruchom scraper"
3. System otworzy `allegro-scraper://start` → Uruchomi scraper

---

## 📊 Jak działa scraper?

```
1. Pobiera listę ofert z API (GET /api/scraper/get_tasks?limit=5)
   → Filtruje tylko oferty gdzie price > 0
   
2. Dla każdej oferty:
   → Otwiera https://allegro.pl/oferta/{id}#inne-oferty-produktu
   → Szuka konkurencyjnych ofert
   → Filtruje: dostawa ≤ 4 dni, cena < nasza cena
   → Losowe opóźnienie 5-15 sekund (anty-ban)
   
3. Wysyła wyniki do API (POST /api/scraper/submit_results)
   → Status: 'competitor_cheaper' | 'cheapest' | 'no_offers'
   → Zapisuje do tabeli allegro_price_history
   
4. Czeka 30 sekund i powtarza
```

---

## 🔒 Bezpieczeństwo / Anty-ban

Scraper ma wbudowane zabezpieczenia:
- ✅ `undetected-chromedriver` (unika detekcji jako bot)
- ✅ Rotacja 4 user-agentów (Chrome/Firefox, Windows/Mac)
- ✅ Losowe opóźnienia 5-15 sekund między ofertami
- ✅ Batch size = 5 (nie 10+, żeby nie przeciążać)
- ✅ Detekcja blokady IP ("zostałeś zablokowany")
- ✅ Auto-stop przy blokadzie (zapisuje częściowe wyniki)

---

## 📝 Changelog

### v2.0 - Smart Bootstrap
- ✅ Auto-instalacja Pythona
- ✅ Auto-wykrywanie Chrome w dowolnej lokalizacji
- ✅ Auto-instalacja zależności
- ✅ Fallback: undetected-chromedriver → selenium
- ✅ Szczegółowe komunikaty błędów
- ✅ Zero konfiguracji - działa "out of the box"

### v1.0 - Podstawowa wersja
- Ręczna instalacja Pythona
- Ręczna instalacja pakietów
- Hardcoded ścieżki Chrome

---

## 💡 FAQ

**Q: Muszę mieć Pythona?**  
A: Nie! `BOOTSTRAP.bat` zainstaluje go automatycznie.

**Q: Muszę znać ścieżkę do Chrome?**  
A: Nie! Scraper wykryje go automatycznie.

**Q: Czy działa na Windows 11?**  
A: Tak, Windows 10 i 11.

**Q: Czy działa na macOS/Linux?**  
A: Scraper tak, ale pliki `.bat` są tylko Windows.  
Na macOS/Linux uruchom bezpośrednio:
```bash
python3 scraper_worker.py --url https://magazyn.retrievershop.pl
```

**Q: Ile ofert może sprawdzić przed blokiem?**  
A: Z anty-ban measures: ~100-150 ofert (vs. 50-60 wcześniej).

**Q: Czy mogę uruchomić na serwerze bez GUI?**  
A: Tak, ale potrzebujesz headless Chrome:
```python
options.add_argument("--headless")
```

---

## 🚀 Podsumowanie

### Dla przeciętnego użytkownika:
```
1. Kliknij RUN_WORKER.bat
2. Czekaj
3. Działa!
```

### Dla admina:
```
1. Kliknij RUN_WORKER.bat
2. Scraper sam:
   - Zainstaluje Pythona (jeśli brak)
   - Wykryje Chrome (w dowolnej lokalizacji)
   - Zainstaluje pakiety
   - Uruchomi się
3. Monitoring przez Docker logs na RPI
```

Zero stresu, zero konfiguracji! 🎉
