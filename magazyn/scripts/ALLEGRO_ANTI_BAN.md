# 🛡️ Allegro Anti-Ban Strategy

## Problem
Po przeskanowaniu ~50-60 ofert Allegro blokuje IP wyświetlając stronę "Zostałeś zablokowany".

## Rozwiązanie wdrożone

### 1. **Spowolnienie scrapingu**
- ✅ Losowy delay między ofertami: **5-15 sekund**
- ✅ Zmniejszony batch size: **5 ofert** (było 10)
- ✅ Automatyczne wykrywanie blokady IP

### 2. **Rotacja User-Agents**
```python
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/121.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/121.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Firefox/122.0"
]
```

### 3. **Wykrywanie blokady**
Scraper automatycznie zatrzymuje się gdy wykryje:
- Stronę "Zostałeś zablokowany"
- Tekst "You have been blocked"

## Co zrobić gdy zostaniesz zablokowany?

### **Opcja 1: Poczekaj (najprostsze)**
```
⏰ Odczekaj 30-60 minut
🔄 Uruchom scraper ponownie
```

### **Opcja 2: Zmień IP**
1. **Zrestartuj router** (zwykle zmienia IP)
2. **Użyj VPN** (np. ProtonVPN, NordVPN)
3. **Użyj mobilnego hotspota** (LTE/5G ma inne IP)

### **Opcja 3: Jeszcze wolniejszy scraping**
Edytuj `scraper_worker.py`:
```python
MIN_DELAY_BETWEEN_OFFERS = 10  # było 5
MAX_DELAY_BETWEEN_OFFERS = 30  # było 15
BATCH_SIZE = 3  # było 5
```

## Statystyki

### Przed optymalizacją:
- 2 sekundy między ofertami
- 10 ofert na batch
- **Blokada po ~50-60 ofertach**

### Po optymalizacji:
- 5-15 sekund (random) między ofertami
- 5 ofert na batch
- **Oczekiwane: ~100-150 ofert przed bloką**

### Czas scrapingu:
- **5 ofert = ~60 sekund** (średnio 12s/ofertę)
- **145 ofert = ~29 minut** (przy batch 5)
- **Zalecane**: uruchamiaj scraper co **2-3 godziny**

## Dodatkowe wskazówki

### ✅ **Dobre praktyki:**
1. Uruchamiaj scraper w godzinach nocnych (mniejszy ruch)
2. Nie sprawdzaj wszystkich 145 ofert naraz
3. Priorytetyzuj oferty z największą konkurencją
4. Używaj `undetected-chromedriver`

### ❌ **Unikaj:**
1. Uruchamiania scrapera kilka razy dziennie z tego samego IP
2. Sprawdzania ofert w godzinach szczytu (12-18)
3. Otwierania wielu okien Chrome z Allegro jednocześnie

## Monitorowanie

Scraper automatycznie wyświetla:
```
⛔ IP BLOCKED BY ALLEGRO!
Your IP has been blocked by Allegro's anti-bot protection.

RECOMMENDATIONS:
1. Wait 30-60 minutes before retrying
2. Use VPN or change IP address
3. Reduce scraping speed
```

## Przyszłe ulepszenia (opcjonalne)

### **Opcja A: Proxy rotation**
- Kup rotating proxy (np. Bright Data, Oxylabs)
- Koszt: ~$50-100/miesiąc
- Nielimitowane requesty

### **Opcja B: Residential proxies**
- Prawdziwe IP domowe
- Bardzo trudne do wykrycia
- Koszt: $100-300/miesiąc

### **Opcja C: Wielowątkowy scraping**
- Wiele VPN/proxy jednocześnie
- Każdy wątek: 3-5 ofert
- Całość: ~10 minut dla 145 ofert

### **Opcja D: API Allegro (najlepsze)**
- Oficjalne API Allegro
- Brak blokad
- Limit: 9000 requestów/dzień
- **Problem**: API nie pokazuje cen konkurencji 🚫

## Podsumowanie

### Obecne ustawienia:
```python
BATCH_SIZE = 5
MIN_DELAY = 5 sekund
MAX_DELAY = 15 sekund
USER_AGENTS = 4 różne
```

### Zalecana częstotliwość:
- **Co 2-3 godziny** dla pełnego skanowania
- **Lub 24/7** z bardzo wolnym tempem (20-30s delay)

---

**Ostatnia aktualizacja**: 2025-12-28  
**Commit**: f983704
