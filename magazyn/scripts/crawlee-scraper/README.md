# Crawlee Allegro Scraper

Scraper cen konkurentow Allegro oparty na [Crawlee](https://crawlee.dev/) od Apify.

## Zalety Crawlee

- **Automatyczny fingerprint spoofing** - zmienia fingerprint przegladarki
- **Human-like behavior** - naturalnie wyglada dla bot protection
- **Integracja z Camoufox** - dla trudnych stron (DataDome, Cloudflare)
- **handleCloudflareChallenge** - automatyczne rozwiazywanie captcha
- **HTTP2 + TLS fingerprint** - imituje prawdziwa przegladarke
- **Proxy rotation** - wbudowane zarzadzanie proxy
- **Persistentna kolejka** - nie gubi URLi przy restartach

## Instalacja

```bash
cd magazyn/scripts/crawlee-scraper
npm install

# Zainstaluj przegladarki Playwright
npx playwright install chromium
```

### Opcjonalnie: Camoufox (dla DataDome)

```bash
npm install camoufox-js
npx camoufox fetch
```

## Uzycie

```bash
# Test
npm run test

# Scraping pojedynczego URL
npx tsx src/main.ts "https://allegro.pl/oferta/..."

# Z Camoufox (lepszy stealth)
npx tsx src/main.ts "https://allegro.pl/oferta/..." --camoufox

# Z proxy
npx tsx src/main.ts "https://allegro.pl/oferta/..." --proxy=http://user:pass@host:port
```

## Porownanie z innymi metodami

| Metoda | Stealth | JS Rendering | Latwosc | Koszt |
|--------|---------|--------------|---------|-------|
| Stealth-Requests | Sredni | Brak | Latwe | Darmowe |
| Selenium | Niski | Tak | Srednie | Darmowe |
| Camoufox standalone | Wysoki | Tak | Trudne | Darmowe |
| **Crawlee + Camoufox** | **Wysoki** | **Tak** | **Latwe** | **Darmowe** |
| Oxylabs/Browserless | Wysoki | Tak | Latwe | Platne |

## Integracja z magazyn

Scraper mozna wywolac z Pythona:

```python
import subprocess
import json

result = subprocess.run(
    ['npx', 'tsx', 'src/main.ts', offer_url],
    cwd='magazyn/scripts/crawlee-scraper',
    capture_output=True,
    text=True
)

if result.returncode == 0:
    data = json.loads(result.stdout)
    print(f"Najtanszy: {data['cheapest']['seller']} @ {data['cheapest']['price']}")
```

## Docker

```dockerfile
FROM apify/actor-node-playwright-chrome:20

WORKDIR /app
COPY package*.json ./
RUN npm install --omit=dev
COPY . .
RUN npm run build

CMD ["node", "dist/main.js"]
```
