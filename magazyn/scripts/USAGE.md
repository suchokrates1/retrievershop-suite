# Allegro Scraper - Instrukcja Użycia

## Przegląd rozwiązania

Scraper omija DataDome używając prawdziwego Chrome z prawdziwą sesją użytkownika.
**Nie używa headless mode** - dlatego DataDome go nie wykrywa.

## Jak to działa?

```
┌─────────────┐         HTTP API          ┌──────────────┐
│   RPI/RPi   │ ─────────────────────────> │   Twój PC    │
│  (magazyn)  │  check_price?url=...      │  (Windows)   │
└─────────────┘                            └──────────────┘
                                                   │
                                                   │ Selenium
                                                   ↓
                                           ┌──────────────┐
                                           │    Chrome    │
                                           │ (logged in)  │
                                           └──────────────┘
                                                   │
                                                   │ HTTPS
                                                   ↓
                                           ┌──────────────┐
                                           │  Allegro.pl  │
                                           │  (DataDome)  │
                                           └──────────────┘
```

## Instalacja (na każdym PC z Windows)

### 1. Pobierz scraper z aplikacji magazyn

- Zaloguj się do http://192.168.31.72:8000/
- Przejdź do **Ustawienia** (menu)
- Przewiń na dół do sekcji **"Allegro Scraper"**
- Kliknij **"Pobierz AllegroScraper_Portable.zip"**

### 2. Rozpakuj i zainstaluj

```batch
1. Rozpakuj ZIP do dowolnego folderu (np. C:\AllegroScraper)
2. Kliknij prawym na SETUP.bat → "Uruchom jako administrator"
3. Poczekaj na instalację pakietów Python
```

Co zostanie zainstalowane:
- selenium (automatyzacja przeglądarki)
- flask (serwer API)
- webdriver-manager (automatyczne pobieranie ChromeDriver)

### 3. Pierwsze uruchomienie

```batch
1. Kliknij 2x na RUN_SCRAPER.bat
2. Otworzy się Chrome - ZALOGUJ SIĘ NA ALLEGRO
3. Po zalogowaniu - zostaw okno otwarte (możesz zminimalizować)
4. Scraper działa! API nasłuchuje na porcie 5555
```

**Ważne:** 
- Używany jest **dedykowany profil Chrome** (`allegro_scraper_profile/`)
- Nie koliduje z Twoim codziennym Chrome/Brave
- Sesja jest zapisana - logujesz się tylko raz

## Użycie z RPI

### Sprawdzanie ceny oferty

```bash
curl "http://192.168.31.150:5555/check_price?url=https://allegro.pl/oferta/17892897249"
```

Odpowiedź sukces:
```json
{
  "success": true,
  "url": "https://allegro.pl/oferta/17892897249",
  "price": "159.89",
  "timestamp": "20251221_123456",
  "html_saved": "scraped_20251221_123456.html"
}
```

Odpowiedź captcha:
```json
{
  "error": "CAPTCHA detected",
  "message": "Please solve captcha manually in Chrome window and retry"
}
```

### Integracja z Python (magazyn app)

```python
import requests

def check_allegro_price(offer_url, pc_ip="192.168.31.150"):
    """Check Allegro offer price using local scraper"""
    try:
        response = requests.get(
            f"http://{pc_ip}:5555/check_price",
            params={"url": offer_url},
            timeout=30
        )
        
        if response.status_code == 200:
            data = response.json()
            return data.get("price")
        elif response.status_code == 503:
            # CAPTCHA - send notification to solve
            print("CAPTCHA detected - manual solve needed")
            return None
        else:
            print(f"Error: {response.json()}")
            return None
            
    except requests.exceptions.RequestException as e:
        print(f"Connection error: {e}")
        return None

# Usage
price = check_allegro_price("https://allegro.pl/oferta/17892897249")
if price:
    print(f"Price: {price} zł")
```

## API Endpoints

### GET /check_price
Sprawdza cenę oferty Allegro

**Parameters:**
- `url` (required) - pełny URL oferty Allegro

**Response 200 OK:**
```json
{
  "success": true,
  "price": "159.89",
  "url": "https://...",
  "timestamp": "20251221_123456",
  "html_saved": "scraped_20251221_123456.html"
}
```

**Response 503 Service Unavailable (CAPTCHA):**
```json
{
  "error": "CAPTCHA detected",
  "message": "Please solve captcha manually in Chrome window and retry"
}
```

**Response 404 Not Found:**
```json
{
  "error": "Price not found",
  "html_length": 123456
}
```

### GET /status
Sprawdza czy scraper działa

**Response 200 OK:**
```json
{
  "status": "running",
  "driver_active": true
}
```

### POST /restart
Restartuje Chrome driver (np. po rozwiązaniu captcha)

**Response 200 OK:**
```json
{
  "status": "driver restarted"
}
```

## Uruchamianie na wielu komputerach

Możesz uruchomić scraper na kilku komputerach jednocześnie:

```python
SCRAPER_POOL = [
    "192.168.31.150",  # Laptop
    "192.168.31.151",  # Desktop
    "192.168.31.152",  # Inny PC
]

def check_price_distributed(offer_url):
    """Try scrapers from pool until one succeeds"""
    import random
    random.shuffle(SCRAPER_POOL)
    
    for pc_ip in SCRAPER_POOL:
        price = check_allegro_price(offer_url, pc_ip)
        if price:
            return price
    
    return None  # All failed
```

## Troubleshooting

### "Connection refused"
**Problem:** RPI nie może połączyć się z PC
**Rozwiązanie:**
1. Sprawdź czy RUN_SCRAPER.bat działa
2. Sprawdź firewall Windows - dodaj wyjątek dla portu 5555
3. Sprawdź IP PC: `ipconfig` i użyj właściwego w URL

### "CAPTCHA detected" co kilka minut
**Problem:** DataDome rate-limiting
**Rozwiązanie:**
1. Dodaj opóźnienie między requestami (10-15 sekund)
2. Użyj cache'owania wyników (nie pytaj o tę samą ofertę częściej niż raz na 5 minut)
3. Uruchom kilka scraperów na różnych PC

### Chrome się nie otwiera
**Problem:** Konflikt z istniejącą sesją
**Rozwiązanie:**
1. Zamknij całkowicie Chrome (sprawdź Task Manager)
2. Usuń folder `allegro_scraper_profile`
3. Uruchom ponownie RUN_SCRAPER.bat

### "Price not found"
**Problem:** Allegro zmieniło layout strony
**Rozwiązanie:**
1. Otwórz zapisany HTML (`scraped_*.html`)
2. Znajdź cenę w HTML
3. Dodaj nowy pattern do `parse_price()` w `scraper_api.py`

## Bezpieczeństwo

- Scraper działa tylko w sieci lokalnej (0.0.0.0:5555)
- Brak hasła do API - dostęp tylko z LAN
- Sesja Allegro w dedykowanym profilu Chrome
- Zapisywane HTML (dla debugowania) zawiera dane sesji - nie udostępniaj

## Wydajność

- Pierwsze uruchomienie: ~5 sekund (Chrome init)
- Kolejne requesty: ~3-5 sekund (reuse session)
- CAPTCHA (rzadko): ~30 sekund (manual solve)
- Rate limit: max ~5-10 requestów/minutę (bezpieczny poziom)

## Utrzymanie

Scraper nie wymaga update'ów - działa z każdą wersją Chrome/Allegro.
Jedyne co może się zmienić to HTML structure Allegro (pattern matching ceny).
