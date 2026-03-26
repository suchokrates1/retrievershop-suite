# Plan migracji stacku technologicznego - retrievershop-suite

**Data utworzenia**: 2026-03-26
**Ostatnia aktualizacja**: 2026-03-26
**Autor**: Dawid Suchodolski + Copilot

---

## Filozofia

Skala projektu: 1-2 uzytkownikow, kilkaset zamowien miesiecznie, integracje Allegro/wFirma/InPost.
Nie potrzebujemy mikroserwisow, Kubernetesa ani SPA. Kazda zmiana musi byc przyrostowa
i odwracalna. Flask + Bootstrap + Docker Compose to wlasciwy stack dla tej skali.

## Obecna architektura

| Komponent | Obecne rozwiazanie | Docelowe | Priorytet |
|-----------|-------------------|----------|-----------|
| Baza danych | SQLite (WAL) | **PostgreSQL 16** | KRYTYCZNY |
| Framework | Flask 3.0.3 + Gunicorn | Flask (zostaje) | - |
| Frontend JS | Vanilla JS + Alpine.js | Alpine.js + **htmx** | WYSOKI |
| UI Framework | Bootstrap 5 (czyste) | **Tabler** (motyw Bootstrap) | SREDNI |
| Kolejka zadan | SQLite `label_queue` | APScheduler (zostaje) | NISKI |
| Cache | Brak | Opcjonalnie Redis w przyszlosci | NISKI |
| Deploy | git pull + docker compose | **GitHub Actions -> SSH** | WYSOKI |
| Monitoring | Grafana + Loki + Promtail | Zostaje + backup PostgreSQL | OK |
| Reverse proxy | Traefik (HA minipc+RPI5) | Zostaje | OK |

**Decyzje:**
- **FastAPI** - odrzucone. Migracja z Flask to duzy koszt, brak proporcjonalnych korzysci przy tej skali.
- **Celery + Redis** - odlozone. APScheduler wystarcza. Celery oplacalby sie przy wiekszej liczbie background jobs.
- **VPS zamiast minipc** - do rozwazeina w przyszlosci. Na razie minipc spelnia wymagania.

## Serwer produkcyjny

- **minipc** (GMKtec NucBox G3): Intel N100, 16GB RAM, NVMe 477GB
- **IP**: 192.168.31.5
- **Kontener**: `retrievershop-magazyn` (port 8000)
- **Domena**: magazyn.retrievershop.pl (Cloudflare tunnel + Traefik)

---

## Faza 1: SQLite -> PostgreSQL

### Cel
Wyeliminowanie glownego waskiego gardla - SQLite pozwala na 1 zapis naraz.
PostgreSQL da wspolbieznosc, replikacje, pelnotekstowe wyszukiwanie, JSONB.

### Kroki

1. **Dodac serwis PostgreSQL do docker-compose.yml**
   ```yaml
   postgres:
     image: postgres:16-alpine
     container_name: retrievershop-postgres
     environment:
       POSTGRES_DB: magazyn
       POSTGRES_USER: magazyn
       POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
     volumes:
       - postgres_data:/var/lib/postgresql/data
     networks:
       - proxy
     restart: always
     healthcheck:
       test: ["CMD-SHELL", "pg_isready -U magazyn"]
       interval: 10s
       timeout: 5s
       retries: 5
   ```

2. **Zmienic connection string w .env**
   ```
   DATABASE_URL=postgresql://magazyn:${POSTGRES_PASSWORD}@postgres:5432/magazyn
   ```

3. **Zaktualizowac `magazyn/db.py`**
   - SQLAlchemy 2.0 juz obsluguje PostgreSQL - wystarczy zmienic URL
   - Usunac `connect_args={"check_same_thread": False}` (specyficzne dla SQLite)
   - Dodac pool_size i max_overflow

4. **Migracja danych**
   - Skrypt `scripts/migrate_sqlite_to_postgres.py`:
     - Eksport SQLite -> SQL/CSV
     - Import do PostgreSQL z zachowaniem sekwencji ID
   - Uruchomic na kopii bazy najpierw (dry run)

5. **Dostosowac Alembic**
   - `alembic.ini`: zmienic `sqlalchemy.url`
   - Sprawdzic czy migracje sa kompatybilne (BOOLEAN -> bool, TEXT -> text)

6. **Testy**
   - Uruchomic pelny zestaw 394 testow na PostgreSQL
   - Przetestowac: zamowienia, zwroty, faktury, etykiety, scheduler

### Ryzyko
- **Srednie** - SQLAlchemy abstrahuje roznice miedzy silnikami
- **Uwaga**: Sprawdzic czy sa raw SQL queries uzywajace `sqlite_` specyficznych funkcji

### Dodac do requirements.txt
```
psycopg2-binary==2.9.9
```

---

## Faza 2: htmx - reaktywny frontend bez SPA

### Cel
Dodac interaktywnosc (live search, inline edycja, lazy loading) bez pisania JS.
htmx dziala z Jinja2 - zero przepisywania istniejacych templatek.

### Kroki

1. **Dodac htmx do base.html**
   ```html
   <script src="https://unpkg.com/htmx.org@2.0.4"></script>
   ```

2. **Przyrostowa migracja - najpierw:**
   - **Wyszukiwanie zamowien** (`/orders`): `hx-get` z debounce zamiast pelnego przeladowania
   - **Lista produktow**: infinite scroll zamiast paginacji
   - **Edycja inline**: statusy, notatki, ceny bez przechodzenia do podstrony

3. **Nowe endpointy (partiale)**
   - `/orders/partial/list` - fragment HTML z lista zamowien
   - `/products/partial/search` - wyniki wyszukiwania produktow
   - Kazdy partial to Jinja2 template bez base.html (sam fragment)

### Zasady
- Nie lamac istniejacego flow - htmx dodawany obok, nie zamiast
- Kazda strona musi dzialac bez JS (progressive enhancement)
- Alpine.js + htmx wspolpracuja - Alpine dla stanu lokalnego, htmx dla serwera

---

## Faza 3: Tabler - motyw dashboard UI

### Cel
Zamiana czystego Bootstrap 5 na Tabler (https://tabler.io) - gotowy motyw dashboard.
Drop-in replacement, bazuje na Bootstrap, ladniejszy layout, gotowe komponenty (karty, wykresy, tabele).

### Kroki

1. **Instalacja** - zastapic CDN Bootstrap na CDN Tabler
   ```html
   <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@tabler/core@1.0.0-beta20/dist/css/tabler.min.css">
   <script src="https://cdn.jsdelivr.net/npm/@tabler/core@1.0.0-beta20/dist/js/tabler.min.js"></script>
   ```

2. **Migracja base.html**
   - Zamiana layoutu na Tabler sidebar + header
   - Klasy Bootstrap (`container`, `row`, `col`) zostaja - Tabler je rozszerza

3. **Przyrostowa zamiana komponentow**
   - Tabele -> Tabler responsive tables
   - Karty -> Tabler cards z headerami
   - Badge -> Tabler status dots
   - Dashboard -> Tabler grid + charts

### Ryzyko
- **Srednie** - moze wymagac dopasowania customowych CSS
- Testowac na kazdej stronie osobno

---

## Faza 4: GitHub Actions CI/CD

### Cel
Automatyczny deploy po pushu na main. Zamiast recznego `ssh minipc && git pull && docker compose up`.

### Kroki

1. **Utworzyc `.github/workflows/deploy.yml`**
   ```yaml
   name: Deploy
   on:
     push:
       branches: [main]
   jobs:
     test:
       runs-on: ubuntu-latest
       steps:
         - uses: actions/checkout@v4
         - uses: actions/setup-python@v5
           with:
             python-version: '3.12'
         - run: pip install -r requirements.txt
         - run: python -m pytest magazyn/tests/ -x
     deploy:
       needs: test
       runs-on: ubuntu-latest
       steps:
         - name: Deploy via SSH
           uses: appleboy/ssh-action@v1
           with:
             host: ${{ secrets.MINIPC_HOST }}
             username: suchokrates1
             key: ${{ secrets.SSH_KEY }}
             script: |
               cd /home/suchokrates1/retrievershop-suite
               git pull
               docker compose up -d --build magazyn_app
   ```

2. **Dodac sekrety w GitHub**
   - `MINIPC_HOST` - IP lub Tailscale adres
   - `SSH_KEY` - klucz prywatny

3. **Dodac health check po deployu**
   - Curl `/healthz` po 30s od deployu
   - Notyfikacja na Messenger gdy padnie

---

## Faza 5: Backup PostgreSQL + monitoring

### Cel
Automatyczny backup bazy + powiadomienia o bledach.

### Kroki

1. **Cron backup** (po Fazie 1 - PostgreSQL)
   ```bash
   # /etc/cron.d/postgres-backup
   0 3 * * * docker exec retrievershop-postgres pg_dump -U magazyn magazyn | gzip > /backup/magazyn_$(date +\%Y\%m\%d).sql.gz
   ```

2. **Rotacja backupow**
   - Lokalne: 7 dni
   - NAS (192.168.31.4): 30 dni
   - **UWAGA**: NAS ma RAID0 - rozwazyc offsite backup (S3/Backblaze)

3. **Monitoring**
   - Uptime Kuma (juz mamy na VPS) - dodac check `/healthz`
   - Sentry free tier - lapie bledy z tracebackami i powiadamia email

---

## Kolejnosc wdrazania

```
Faza 1 (PostgreSQL) -----> Faza 5 (Backup PG)
                                              
Faza 2 (htmx)       \                        
                      >---> rownolegle        
Faza 3 (Tabler)     /                        
                                              
Faza 4 (GitHub Actions) --- niezalezne        
```

- **Faza 1** jest jedyna KRYTYCZNA - reszta to usprawnienia
- Fazy 2, 3, 4 mozna realizowac rownolegle i przyrostowo
- Faza 5 zalezy od Fazy 1 (backup PostgreSQL)

---

## Wymagania sprzetowe

Obecny minipc (N100 / 16GB RAM) powinien obsluzyc caly stack:

| Serwis | Szacowane RAM | CPU |
|--------|--------------|-----|
| Flask + Gunicorn (6 workerow) | ~600 MB | niska |
| PostgreSQL | ~256 MB | niska |
| Redis | ~128 MB | minimalna |
| Celery worker (2 procesy) | ~400 MB | niska |
| Celery beat | ~100 MB | minimalna |
| **Razem nowy stack** | **~1.5 GB** | <50% N100 |

Mamy 16 GB RAM - duzy zapas.

---

## Migracja danych - plan dzialania

1. Zrobic backup SQLite: `cp database.db database.db.bak`
2. Uruchomic PostgreSQL (pusty)
3. Uruchomic migracje Alembic na PostgreSQL
4. Uruchomic skrypt migracji danych (INSERT z SQLite -> PostgreSQL)
5. Zweryfikowac liczby rekordow we wszystkich tabelach
6. Przelaczenie flagi DATABASE_URL
7. Testy na produkcji (10 min obserwacji)
8. Jesli blad: cofniecie na SQLite (zmiana DATABASE_URL)

**Czas przestoju**: ~5-10 minut (kopiowanie danych + restart)
**Rollback**: Zmiana 1 linii w .env + restart kontenera
