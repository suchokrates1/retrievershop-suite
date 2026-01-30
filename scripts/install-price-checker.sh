#!/bin/bash
# =============================================================================
# PRICE CHECKER - INSTALACJA NA MINIPC
# =============================================================================
#
# Ten skrypt instaluje price checker z przegladarka Chrome/VNC na minipc.
# Po instalacji mozesz podgladac przegladarke przez VNC i zarzadzac scrapingiem.
#
# UZYCIE:
#   scp install-price-checker.sh minipc:~
#   ssh minipc "chmod +x install-price-checker.sh && ./install-price-checker.sh"
#
# =============================================================================

set -e

echo "=============================================="
echo "PRICE CHECKER - INSTALACJA"
echo "=============================================="

# Katalog instalacji
INSTALL_DIR="$HOME/price-checker"
mkdir -p "$INSTALL_DIR"
cd "$INSTALL_DIR"

echo "[1/5] Tworzenie docker-compose.yml..."

cat > docker-compose.yml << 'EOF'
# Price Checker z Chrome + VNC
# Podglad przegladarki: http://minipc:7900 (haslo: secret)
# lub VNC client na port 5900

version: "3.8"

services:
  # Chrome z noVNC (podglad przez przegladarke)
  chrome:
    image: selenium/standalone-chrome:latest
    container_name: price-checker-chrome
    hostname: price-checker
    ports:
      - "5900:5900"   # VNC (klient VNC)
      - "7900:7900"   # noVNC (przegladarka webowa)
      - "4444:4444"   # Selenium WebDriver
    environment:
      - SE_VNC_PASSWORD=secret
      - SE_SCREEN_WIDTH=1920
      - SE_SCREEN_HEIGHT=1080
      - SE_NODE_MAX_SESSIONS=1
      - SE_SESSION_REQUEST_TIMEOUT=300
      - SE_SESSION_RETRY_INTERVAL=2
      - VNC_NO_PASSWORD=1
    volumes:
      - chrome-profile:/home/seluser/.config/google-chrome
      - ./downloads:/home/seluser/Downloads
    shm_size: "2gb"
    restart: unless-stopped
    networks:
      - price-checker-net
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:4444/status"]
      interval: 30s
      timeout: 10s
      retries: 3

  # Scraper Python
  scraper:
    build:
      context: .
      dockerfile: Dockerfile.scraper
    container_name: price-checker-scraper
    depends_on:
      chrome:
        condition: service_healthy
    environment:
      - SELENIUM_URL=http://chrome:4444
      - DATABASE_URL=postgresql://magazyn:magazyn@host.docker.internal:5432/magazyn
      - PYTHONUNBUFFERED=1
    volumes:
      - ./scripts:/app/scripts:ro
      - ./logs:/app/logs
      - ./data:/app/data
    networks:
      - price-checker-net
    extra_hosts:
      - "host.docker.internal:host-gateway"
    restart: unless-stopped

volumes:
  chrome-profile:
    name: price-checker-chrome-profile

networks:
  price-checker-net:
    name: price-checker-network
EOF

echo "[2/5] Tworzenie Dockerfile.scraper..."

cat > Dockerfile.scraper << 'EOF'
FROM python:3.11-slim

WORKDIR /app

# Zainstaluj zaleznosci
RUN pip install --no-cache-dir \
    selenium \
    sqlalchemy \
    psycopg2-binary \
    requests \
    schedule

# Skopiuj skrypty
COPY scripts/ /app/scripts/

# Domyslna komenda - czekaj (mozna uruchamiac skrypty reczne)
CMD ["tail", "-f", "/dev/null"]
EOF

echo "[3/5] Tworzenie katalogow..."
mkdir -p scripts logs data downloads

echo "[4/5] Tworzenie glownego skryptu scrapera..."

cat > scripts/price_checker.py << 'PYTHON_EOF'
#!/usr/bin/env python3
"""
Price Checker - sprawdza ceny konkurencji na Allegro.

Uzywa Selenium + Chrome przez Docker.
Chrome musi byc zalogowany na Allegro (przez VNC).

Uzycie:
    # Jednorazowe sprawdzenie
    python price_checker.py --check-all
    
    # Sprawdz konkretna oferte
    python price_checker.py --offer-id 18180401323
    
    # Uruchom scheduler (co godzine)
    python price_checker.py --schedule
"""

import argparse
import json
import logging
import os
import re
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

# Konfiguracja
SELENIUM_URL = os.getenv("SELENIUM_URL", "http://localhost:4444")
MY_SELLER = "Retriever_Shop"
MAX_DELIVERY_DAYS = 4

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("/app/logs/price_checker.log"),
    ]
)
logger = logging.getLogger(__name__)


@dataclass
class CompetitorOffer:
    seller: str
    price: float
    delivery_days: Optional[int] = None
    delivery_text: str = ""
    offer_url: str = ""
    is_super_seller: bool = False


@dataclass
class PriceCheckResult:
    success: bool
    offer_id: str
    my_price: Optional[float] = None
    error: Optional[str] = None
    competitors: List[CompetitorOffer] = None
    cheapest: Optional[CompetitorOffer] = None
    checked_at: str = ""


def get_driver():
    """Tworzy polaczenie z Chrome przez Selenium."""
    options = Options()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    
    driver = webdriver.Remote(
        command_executor=SELENIUM_URL,
        options=options,
    )
    driver.implicitly_wait(10)
    return driver


def parse_delivery_days(text: str) -> Optional[int]:
    """Parsuje tekst dostawy na liczbe dni."""
    if not text:
        return None
    t = text.lower()
    
    if "jutro" in t:
        return 1
    if "dzisiaj" in t:
        return 0
    
    # "za X-Y dni"
    m = re.search(r"za\s+(\d+)\s*-\s*(\d+)\s*dni", t)
    if m:
        return (int(m.group(1)) + int(m.group(2))) // 2
    
    return None


def check_offer(driver, offer_id: str, title: str = "", my_price: float = None) -> PriceCheckResult:
    """Sprawdza ceny konkurencji dla oferty."""
    result = PriceCheckResult(
        success=False,
        offer_id=offer_id,
        my_price=my_price,
        competitors=[],
        checked_at=datetime.now().isoformat(),
    )
    
    try:
        # Zbuduj URL oferty
        if title:
            slug = re.sub(r"[^a-zA-Z0-9]+", "-", title.lower()).strip("-")
            url = f"https://allegro.pl/oferta/{slug}-{offer_id}"
        else:
            url = f"https://allegro.pl/oferta/{offer_id}"
        
        logger.info(f"Otwieram: {url}")
        driver.get(url)
        time.sleep(3)
        
        # Sprawdz czy strona sie zaladowala
        if "captcha" in driver.page_source.lower():
            result.error = "DataDome captcha - zaloguj sie przez VNC"
            return result
        
        # Znajdz link do porownania
        try:
            comparison_link = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'a[href*="/oferty-produktu/"]'))
            )
            comparison_url = comparison_link.get_attribute("href")
        except:
            result.error = "Brak linku do porownania - moze nie ma konkurencji"
            result.success = True
            return result
        
        logger.info(f"Otwieram porownanie: {comparison_url}")
        driver.get(comparison_url)
        time.sleep(3)
        
        # Parsuj dane z JSON w stronie
        html = driver.page_source
        match = re.search(r"__listing_StoreState\s*=\s*({.+?});\s*</script>", html, re.DOTALL)
        
        if match:
            data = json.loads(match.group(1))
            elements = data.get("items", {}).get("elements", [])
            
            for el in elements:
                seller = el.get("seller", {})
                seller_login = seller.get("login", "")
                
                if seller_login.lower() == MY_SELLER.lower():
                    continue
                
                price_info = el.get("price", {}).get("mainPrice", {}) or el.get("price", {})
                try:
                    price = float(price_info.get("amount", 0))
                except:
                    continue
                
                if price <= 0:
                    continue
                
                delivery = el.get("shipping", {}).get("delivery", {})
                delivery_text = delivery.get("label", {}).get("text", "")
                delivery_days = parse_delivery_days(delivery_text)
                
                # Filtruj po czasie dostawy
                if delivery_days is not None and delivery_days > MAX_DELIVERY_DAYS:
                    continue
                
                result.competitors.append(CompetitorOffer(
                    seller=seller_login,
                    price=price,
                    delivery_days=delivery_days,
                    delivery_text=delivery_text,
                    offer_url=el.get("url", ""),
                    is_super_seller=seller.get("superSeller", False),
                ))
        
        # Sortuj i znajdz najtanszego
        result.competitors.sort(key=lambda x: x.price)
        if result.competitors:
            result.cheapest = result.competitors[0]
        
        result.success = True
        logger.info(f"Znaleziono {len(result.competitors)} konkurentow")
        
    except Exception as e:
        result.error = str(e)
        logger.error(f"Blad: {e}")
    
    return result


def main():
    parser = argparse.ArgumentParser(description="Price Checker")
    parser.add_argument("--offer-id", help="ID oferty do sprawdzenia")
    parser.add_argument("--check-all", action="store_true", help="Sprawdz wszystkie oferty z bazy")
    parser.add_argument("--schedule", action="store_true", help="Uruchom scheduler")
    
    args = parser.parse_args()
    
    if args.offer_id:
        driver = get_driver()
        try:
            result = check_offer(driver, args.offer_id)
            print(json.dumps(asdict(result), indent=2, ensure_ascii=False, default=str))
        finally:
            driver.quit()
    
    elif args.check_all:
        logger.info("Sprawdzanie wszystkich ofert...")
        # TODO: Pobierz oferty z bazy i sprawdz
        logger.info("Niezaimplementowane - dodaj polaczenie z baza")
    
    elif args.schedule:
        import schedule
        
        def job():
            logger.info("Uruchamiam zaplanowane sprawdzenie...")
            # TODO: Implementacja
        
        schedule.every(1).hours.do(job)
        logger.info("Scheduler uruchomiony - sprawdzanie co godzine")
        
        while True:
            schedule.run_pending()
            time.sleep(60)
    
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
PYTHON_EOF

echo "[5/5] Tworzenie skryptu pomocniczego..."

cat > start.sh << 'EOF'
#!/bin/bash
# Uruchom price checker

cd "$(dirname "$0")"

case "$1" in
    up)
        docker compose up -d
        echo ""
        echo "=============================================="
        echo "Price Checker uruchomiony!"
        echo ""
        echo "noVNC (przegladarka): http://$(hostname -I | awk '{print $1}'):7900"
        echo "VNC (klient):         $(hostname -I | awk '{print $1}'):5900"
        echo "Haslo VNC:            secret"
        echo ""
        echo "NASTEPNE KROKI:"
        echo "1. Otworz noVNC w przegladarce"
        echo "2. Zaloguj sie na Allegro w Chrome"
        echo "3. Uruchom scraper: ./start.sh check <offer_id>"
        echo "=============================================="
        ;;
    down)
        docker compose down
        ;;
    logs)
        docker compose logs -f
        ;;
    check)
        if [ -z "$2" ]; then
            echo "Uzycie: ./start.sh check <offer_id>"
            exit 1
        fi
        docker exec price-checker-scraper python /app/scripts/price_checker.py --offer-id "$2"
        ;;
    shell)
        docker exec -it price-checker-scraper bash
        ;;
    chrome-shell)
        docker exec -it price-checker-chrome bash
        ;;
    *)
        echo "Uzycie: ./start.sh {up|down|logs|check|shell|chrome-shell}"
        echo ""
        echo "  up           - Uruchom kontenery"
        echo "  down         - Zatrzymaj kontenery"
        echo "  logs         - Pokaz logi"
        echo "  check <id>   - Sprawdz oferte"
        echo "  shell        - Shell w kontenerze scraper"
        echo "  chrome-shell - Shell w kontenerze Chrome"
        ;;
esac
EOF
chmod +x start.sh

echo ""
echo "=============================================="
echo "INSTALACJA ZAKONCZONA!"
echo "=============================================="
echo ""
echo "Katalog: $INSTALL_DIR"
echo ""
echo "NASTEPNE KROKI:"
echo ""
echo "1. Uruchom kontenery:"
echo "   cd $INSTALL_DIR && ./start.sh up"
echo ""
echo "2. Otworz noVNC w przegladarce:"
echo "   http://$(hostname -I | awk '{print $1}'):7900"
echo "   Haslo: secret"
echo ""
echo "3. W Chrome (przez VNC) zaloguj sie na Allegro"
echo ""
echo "4. Sprawdz oferte:"
echo "   ./start.sh check 18180401323"
echo ""
echo "=============================================="
