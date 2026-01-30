# Price Checker - Scraper cen konkurencji Allegro

System do monitorowania cen konkurencji na Allegro z wykorzystaniem przegladarki
z zalogowana sesja i protokolu CDP (Chrome DevTools Protocol).

## Architektura

```
+----------------+     CDP/WebSocket      +------------------+
|    RPI         |  ------------------>   |    minipc        |
|  (baza danych) |     port 9223          | (Chrome + VNC)   |
|                |                        |                  |
| price_checker  |                        | linuxserver/     |
| _ws.py         |                        | chromium         |
+----------------+                        +------------------+
                                                  |
                                                  | HTTP
                                                  v
                                          +------------------+
                                          |    Allegro.pl    |
                                          +------------------+
```

### Komponenty

1. **Chrome na minipc** (`linuxserver/chromium`)
   - Przegladarka z graficznym interfejsem dostepna przez VNC
   - Uzytkownik loguje sie na Allegro przez VNC (https://192.168.31.147:3011)
   - CDP (Chrome DevTools Protocol) wystawiony na port 9223

2. **Scraper na RPI** (`price_checker_ws.py`)
   - Laczy sie z Chrome przez CDP
   - Pobiera oferty z lokalnej bazy danych
   - Nawiguje do stron ofert i parsuje dialog "Inne oferty produktu"
   - Zapisuje wyniki do bazy `AllegroPriceHistory`

## Instalacja

### Na minipc

```bash
# Katalog z konfiguracjami
mkdir -p ~/price-checker/custom-cont-init.d
cd ~/price-checker

# docker-compose.yml jest juz skonfigurowany
docker compose up -d

# Poczekaj na uruchomienie (~30 sekund)
# Sprawdz czy CDP jest dostepny:
curl http://localhost:9222/json
curl http://localhost:9223/json  # proxy na 0.0.0.0
```

### Na RPI

```bash
# Skrypt jest juz w kontenerze retrievershop-suite
docker exec retrievershop-suite pip install websockets
```

## Uzycie

### Logowanie na Allegro

1. Otworz VNC: https://192.168.31.147:3011
2. Zaloguj sie na Allegro w przegladarce Chromium
3. Sesja pozostanie aktywna do czasu wygasniecia cookies

### Sprawdzanie cen

```bash
# Pojedyncza oferta
docker exec retrievershop-suite python /app/magazyn/scripts/price_checker_ws.py \
  --offer-id 17895075509 \
  --cdp-host 192.168.31.147 \
  --cdp-port 9223

# Wszystkie aktywne oferty z bazy (limit 10)
docker exec retrievershop-suite python /app/magazyn/scripts/price_checker_ws.py \
  --check-db \
  --limit 10 \
  --cdp-host 192.168.31.147 \
  --cdp-port 9223

# Wynik jako JSON
docker exec retrievershop-suite python /app/magazyn/scripts/price_checker_ws.py \
  --offer-id 17895075509 \
  --cdp-host 192.168.31.147 \
  --cdp-port 9223 \
  --json
```

### Harmonogram (cron)

Dodaj do crontab na RPI:

```cron
# Sprawdzaj ceny codziennie o 8:00
0 8 * * * docker exec retrievershop-suite python /app/magazyn/scripts/price_checker_ws.py --check-db --limit 50 --cdp-host 192.168.31.147 --cdp-port 9223 >> /var/log/price-checker.log 2>&1
```

## Rozwiazywanie problemow

### CDP niedostepny z zewnatrz

Chrome domyslnie nasluchuje tylko na 127.0.0.1. Rozwiazanie: socat proxy.

```bash
# Wewnatrz kontenera Chrome
docker exec -it price-checker-chrome bash
apt-get update && apt-get install -y socat
socat TCP-LISTEN:9223,bind=0.0.0.0,fork TCP:127.0.0.1:9222 &
```

Skrypt startowy w `/custom-cont-init.d/10-socat.sh` robi to automatycznie.

### Dialog "Inne oferty produktu" nie pojawia sie

- Upewnij sie, ze jestes zalogowany na Allegro
- Niektore oferty nie maja konkurencji (brak dialogu)
- Poczekaj dluzej (timeout domyslnie 15 sekund)

### Blad "Connection refused"

1. Sprawdz czy Chrome dziala: `docker ps | grep price-checker`
2. Sprawdz czy port jest otwarty: `curl http://192.168.31.147:9223/json`
3. Sprawdz firewall na minipc

## Pliki

- `~/price-checker/docker-compose.yml` - konfiguracja Docker na minipc
- `~/price-checker/custom-cont-init.d/10-socat.sh` - skrypt startowy socat
- `/app/magazyn/scripts/price_checker_ws.py` - skrypt scrapera (w kontenerze RPI)

## Porty

| Port | Usluga | Opis |
|------|--------|------|
| 3010 | HTTP VNC | Dostep do przegladarki (HTTP) |
| 3011 | HTTPS VNC | Dostep do przegladarki (HTTPS) |
| 9222 | CDP (wewnetrzny) | Chrome DevTools Protocol (127.0.0.1) |
| 9223 | CDP (zewnetrzny) | Proxy socat (0.0.0.0) |

## Ograniczenia

- Wymaga recznego logowania na Allegro przez VNC
- Sesja wygasa po pewnym czasie (trzeba sie ponownie zalogowac)
- Scraping jest powolny (~30 sekund na oferte)
- Niektore oferty nie maja danych konkurencji
