# Plan migracji: Zastapienie BaseLinker bezposrednia integracja z Allegro

## Spis tresci

1. [Podsumowanie wykonawcze](#1-podsumowanie-wykonawcze)
2. [Architektura obecna vs docelowa](#2-architektura-obecna-vs-docelowa)
3. [Moduly do zbudowania](#3-moduly-do-zbudowania)
4. [Faza 1 - Pobieranie zamowien z Allegro](#4-faza-1---pobieranie-zamowien-z-allegro)
5. [Faza 2 - Wysylam z Allegro (etykiety)](#5-faza-2---wysylam-z-allegro-etykiety)
6. [Faza 3 - Integracja wFirma (faktury)](#6-faza-3---integracja-wfirma-faktury)
7. [Faza 4 - Email do klienta](#7-faza-4---email-do-klienta)
8. [Faza 5 - Aktualizacja statusow Allegro](#8-faza-5---aktualizacja-statusow-allegro)
9. [Faza 6 - Sledzenie przesylek i maile po dostarczeniu](#9-faza-6---sledzenie-przesylek-i-maile-po-dostarczeniu)
10. [Faza 7 - Reczne zamowienia (OLX)](#10-faza-7---reczne-zamowienia-olx)
11. [Zmiany w modelu danych](#11-zmiany-w-modelu-danych)
12. [Pliki do modyfikacji / utworzenia](#12-pliki-do-modyfikacji--utworzenia)
13. [Migracja danych](#13-migracja-danych)
14. [Plan usuwania BaseLinker](#14-plan-usuwania-baselinker)
15. [Zaleznosci zewnetrzne](#15-zaleznosci-zewnetrzne)
16. [Ryzyka i mitygacja](#16-ryzyka-i-mitygacja)

---

## 1. Podsumowanie wykonawcze

**Cel**: Calkowite wyeliminowanie BaseLinker jako posrednika. Allegro REST API staje sie jedynym
zrodlem prawdy dla zamowien. Dodatkowo integrujemy wFirma (faktury) i rozbudowujemy
system o wysylke e-maili transakcyjnych do klientow.

**Zakres**:
- Pobieranie zamowien wylacznie z Allegro (Event-driven + polling)
- Tworzenie etykiet przez "Wysylam z Allegro" (Shipment Management API)
- Wystawianie faktur i wysylka do wFirma przez ich API
- Wysylka emaili do klientow (potwierdzenie, faktura, informacja o wysylce, dostarczenie)
- Zarzadzanie statusami bezposrednio w Allegro (fulfillment.status)
- Sledzenie przesylek przez Allegro Parcel Tracking API
- Formularz recznego tworzenia zamowien (OLX, sprzedaz bezposrednia)

**Obecne zaleznosci od BaseLinker ktore trzeba zastapic**:
| Funkcja BaseLinker | Zastepnik |
|---|---|
| `getOrders` (pobieranie zamowien) | Allegro `GET /order/events` + `GET /order/checkout-forms/{id}` |
| `getPackages` + `getLabel` (etykiety) | Allegro Shipment Management API (`POST /shipment-management/shipments`) |
| `getCourierTracking` (sledzenie) | Allegro `GET /order/carriers/{carrierId}/tracking` (juz zaimplementowane) |
| `setOrderStatus` (statusy) | Allegro `PUT /order/checkout-forms/{id}/fulfillment` |
| `getOrderReturns` (zwroty) | Allegro `GET /order/customer-returns` (juz zaimplementowane) |
| Webhook "Wywolaj URL" (label_failed) | Wlasny polling/event-driven |

---

## 2. Architektura obecna vs docelowa

### Obecna (przez BaseLinker)
```
Allegro <--> BaseLinker <--> Nasza aplikacja
                |                   |
         getOrders             sync_order_from_data()
         getPackages           print_agent.py (etykiety)
         getLabel              agent/tracking.py (sledzenie)
         getCourierTracking    returns.py (zwroty)
         setOrderStatus
```

### Docelowa (bezposrednio Allegro + wFirma)
```
Allegro REST API
    |
    +-- GET /order/events (event-driven polling co 60s)
    +-- GET /order/checkout-forms/{id} (szczegoly)
    +-- PUT /order/checkout-forms/{id}/fulfillment (zmiana statusu)
    +-- POST /order/checkout-forms/{id}/shipments (numer przesylki)
    +-- POST /order/checkout-forms/{id}/invoices (upload faktury)
    +-- GET /order/carriers/{carrierId}/tracking (sledzenie)
    +-- GET /order/customer-returns (zwroty)
    +-- POST /payments/refunds (zwrot platnosci)
    +-- GET /order/carriers (lista przewoznikow)
    |
    +-- Shipment Management API ("Wysylam z Allegro")
         +-- GET /shipment-management/delivery-services (dostepne uslugi)
         +-- POST /shipment-management/shipments (tworzenie przesylki + etykieta)
         +-- GET /shipment-management/shipments/{id} (szczegoly)
         +-- GET /shipment-management/shipments/{id}/label (pobieranie etykiety)
         +-- POST /shipment-management/shipments/commands/cancel (anulowanie)

wFirma API (https://api2.wfirma.pl)
    |
    +-- POST /invoices/add (tworzenie faktury VAT)
    +-- GET /invoices/download/{id} (pobieranie PDF)
    +-- POST /contractors/add (tworzenie kontrahenta)

SMTP (istniejacy)
    |
    +-- Email transakcyjny do klienta
```

---

## 3. Moduly do zbudowania

### Nowe pliki
| Plik | Opis |
|---|---|
| `magazyn/allegro_api/events.py` | Polling dziennika zdarzen (`GET /order/events`) |
| `magazyn/allegro_api/fulfillment.py` | Zmiana statusow realizacji + dodawanie numerow przesylek |
| `magazyn/allegro_api/shipment_management.py` | Integracja "Wysylam z Allegro" - tworzenie przesylek i pobieranie etykiet |
| `magazyn/allegro_api/invoices.py` | Upload faktur do zamowien Allegro |
| `magazyn/allegro_api/carriers.py` | Pobieranie listy przewoznikow |
| `magazyn/wfirma_api/__init__.py` | Pakiet klienta wFirma |
| `magazyn/wfirma_api/client.py` | Klient HTTP wFirma (auth, retry) |
| `magazyn/wfirma_api/invoices.py` | Tworzenie faktur VAT, pobieranie PDF |
| `magazyn/wfirma_api/contractors.py` | Zarzadzanie kontrahentami |
| `magazyn/services/order_pipeline.py` | Glowny pipeline obslugi zamowienia (orkiestrator) |
| `magazyn/services/email_service.py` | Wysylka emaili transakcyjnych (szablony HTML) |
| `magazyn/services/label_service.py` | Nowy serwis etykiet (bez BaseLinker) |
| `magazyn/blueprints/manual_orders.py` | Blueprint formularza recznych zamowien |
| `magazyn/templates/manual_order_form.html` | Szablon formularza recznego zamowienia |
| `magazyn/templates/emails/` | Szablony emaili (potwierdzenie, wysylka, faktura, dostarczenie) |

### Pliki do duzej modyfikacji
| Plik | Zakres zmian |
|---|---|
| `magazyn/orders.py` | Usuniecie `_sync_orders_from_baselinker()`, nowy sync z eventow Allegro |
| `magazyn/order_sync_scheduler.py` | Nowy scheduler oparty na eventach zamiast polling BaseLinker |
| `magazyn/print_agent.py` | Wymiana `call_api()` BaseLinker na Allegro Shipment Management |
| `magazyn/agent/tracking.py` | Usuniecie BaseLinker `getCourierTracking`, uzycie Allegro tracking |
| `magazyn/returns.py` | Usuniecie `check_baselinker_order_returns()`, Allegro customer-returns |
| `magazyn/models.py` | Nowe pola (allegro_checkout_form_id jako PK, invoice_id, itp.) |
| `magazyn/settings_store.py` | Nowe klucze wFirma, usuniecie API_TOKEN BaseLinker |
| `magazyn/diagnostics.py` | Usuniecie webhooka BaseLinker |

### Pliki do usuniecia (po zakonczeniu migracji)
- Referencje do BaseLinker w `print_agent.py` (call_api, getOrders, getPackages, getLabel)
- `BASELINKER_STATUS_MAP`, `ALL_STATUS_IDS`, `ACTIVE_STATUS_IDS` z `orders.py`
- `BASELINKER_API_URL` z `agent/tracking.py`
- `API_TOKEN`, `BASELINKER_WEBHOOK_TOKEN` z settings

---

## 4. Faza 1 - Pobieranie zamowien z Allegro

### Cel
Zastapic `_sync_orders_from_baselinker()` mechanizmem event-driven opartym na Allegro Events API.

### Mechanizm: Event-driven polling

**Dlaczego events zamiast checkout-forms list?**
- Events API pozwala na inkrementalne pobieranie zmian (parametr `from={last_seen_event_id}`)
- Nie ma limitu 10000 (offset+limit) jak w checkout-forms
- Wykrywa zmiany statusow, anulowania, aktualizacje FOD
- Allegro zaleca events jako glowny mechanizm monitorowania zamowien

### Implementacja: `allegro_api/events.py`

```python
# Nowy modul - polling dziennika zdarzen
def fetch_order_events(*, from_event_id=None, event_types=None, limit=100):
    """
    GET /order/events
    
    Parametry:
    - from: ID ostatniego przetworzonego zdarzenia (inkrementalne)
    - type: BOUGHT, FILLED_IN, READY_FOR_PROCESSING, BUYER_CANCELLED, 
            FULFILLMENT_STATUS_CHANGED, AUTO_CANCELLED
    - limit: 1-1000 (domyslnie 100)
    
    Zwraca liste zdarzen z checkoutForm.id
    """

def fetch_event_stats():
    """
    GET /order/event-stats
    
    Zwraca info o najnowszym zdarzeniu (do detekcji czy sa nowe eventy).
    """
```

### Implementacja: Nowy scheduler w `order_sync_scheduler.py`

```python
def _sync_from_allegro_events(app):
    """
    1. Wczytaj last_event_id z settings_store
    2. Wywolaj GET /order/events?from={last_event_id}&limit=1000
    3. Dla kazdego zdarzenia READY_FOR_PROCESSING:
       a. Pobierz szczegoly: GET /order/checkout-forms/{checkoutForm.id}
       b. Parsuj przez parse_allegro_order_to_data()
       c. Zapisz/aktualizuj w bazie przez sync_order_from_data()
       d. Ustaw status = "pobrano"
       e. Uruchom pipeline (etykieta, faktura, email)
    4. Dla zdarzen BUYER_CANCELLED / AUTO_CANCELLED:
       a. Zaktualizuj status na "anulowano"
    5. Dla FULFILLMENT_STATUS_CHANGED:
       a. Zaktualizuj status wewnetrzny
    6. Zapisz last_event_id do settings_store
    
    Interwal: co 60 sekund (zamiast co godzine)
    """
```

### Zmiana klucza glownego Order

Obecne: `order_id` = BaseLinker ID (np. "12345678")
Nowe: `order_id` = `allegro_{checkout_form_uuid}` (format juz uzywany przez `parse_allegro_order_to_data()`)

Nie trzeba zmieniac schematu - `parse_allegro_order_to_data()` juz generuje `order_id = f"allegro_{cf_id}"`.

### Kluczowe zachowania
- Zdarzenie `READY_FOR_PROCESSING` = zamowienie oplacone, mozna realizowac
- Zdarzenie `FILLED_IN` = FOD wypelniony ale platnosc moze sie zmienic - NIE przetwarzamy
- Zdarzenia moga przychodzic w nieoczekiwanej kolejnosci (Allegro to potwierdza)
- Duplikaty zdarzen identyfikowac po `type` + `occurredAt`
- Kupujacy moze polaczyc 2 zakupy w 1 zamowienie (nowe `checkoutForm.id`) - trzeba obsluzyc

---

## 5. Faza 2 - Wysylam z Allegro (etykiety)

### Cel
Zastapic BaseLinker `getPackages` + `getLabel` bezposrednia integracja z Allegro Shipment Management API.

### Tlo
"Wysylam z Allegro" to wbudowana usluga Allegro pozwalajaca tworzyc przesylki i generowac
etykiety bezposrednio przez API. Wspolpracuje z przewoznikami: InPost, DPD, DHL, Poczta Polska,
Orlen Paczka, Allegro One Box/Punkt, i innymi.

### Endpointy Shipment Management API

| Endpoint | Metoda | Opis |
|---|---|---|
| `/shipment-management/delivery-services` | GET | Lista dostepnych uslug dostawy (przewoznicy + metody) |
| `/shipment-management/shipments` | POST | Utworzenie przesylki (generuje etykiete) |
| `/shipment-management/shipments/{shipmentId}` | GET | Szczegoly przesylki (status, waybill) |
| `/shipment-management/shipments/{shipmentId}/label` | GET | Pobranie etykiety (PDF) |
| `/shipment-management/shipments/commands/cancel` | PUT | Anulowanie przesylki |

### Implementacja: `allegro_api/shipment_management.py`

```python
def get_delivery_services(access_token):
    """
    GET /shipment-management/delivery-services
    
    Zwraca liste dostepnych przewoznikow i metod dostawy.
    Kazda usluga ma: id, name, carrier (id, name), 
    supportedFormats (label formats).
    
    Cachujemy lokalne na 24h (rzadko sie zmienia).
    """

def create_shipment(access_token, *, checkout_form_id, delivery_service_id,
                    sender, receiver, packages, pickup=None):
    """
    POST /shipment-management/shipments
    
    Tworzy przesylke na podstawie zamowienia.
    
    Body:
    {
        "deliveryServiceId": "...",
        "checkoutForm": {"id": "uuid-zamowienia"},
        "sender": {
            "name": "Retriever Shop",
            "street": "...", "city": "...", "zipCode": "...",
            "countryCode": "PL", "phone": "...", "email": "..."
        },
        "receiver": {
            "name": "Jan Kowalski",
            "street": "...", "city": "...", "zipCode": "...",
            "countryCode": "PL", "phone": "...", "email": "...",
            "pickupPointId": "POZ08A"  # jesli paczkomat/punkt
        },
        "packages": [
            {"weight": {"value": 1.0, "unit": "KILOGRAM"},
             "dimensions": {"length": 30, "width": 20, "height": 10, "unit": "CENTIMETER"}}
        ],
        "pickup": {
            "date": "2026-03-15",  # data odbioru (opcjonalne)
        }
    }
    
    Zwraca: shipmentId (do monitorowania statusu i pobierania etykiety)
    """

def get_shipment_details(access_token, shipment_id):
    """
    GET /shipment-management/shipments/{shipmentId}
    
    Zwraca status przesylki + waybill (numer listu przewozowego).
    Status moze byc: DRAFT, CONFIRMED, DISPATCHED, DELIVERED, CANCELLED.
    
    packages[].waybill - numer przesylki do sledzenia
    """

def get_shipment_label(access_token, shipment_id, *, label_format="PDF"):
    """
    GET /shipment-management/shipments/{shipmentId}/label
    
    Accept: application/pdf (lub application/zpl)
    
    Zwraca binarny plik etykiety do wydrukowania.
    """

def cancel_shipment(access_token, *, shipment_ids):
    """
    PUT /shipment-management/shipments/commands/cancel
    
    Anuluje przesylke (jesli jeszcze nie odebrana przez kuriera).
    """
```

### Nowy serwis: `services/label_service.py`

```python
class AllegroLabelService:
    """
    Zastepuje LabelAgent.get_order_packages() + get_label()
    
    Flow:
    1. Pobierz delivery_services (cachowane)
    2. Dopasuj delivery_service_id na podstawie delivery_method zamowienia
    3. Utworz shipment (POST /shipment-management/shipments)
    4. Poczekaj na potwierdzenie (status CONFIRMED)
    5. Pobierz etykiete (GET .../label)
    6. Wydrukuj na CUPS (istniejaca logika print_label())
    7. Zapisz waybill do zamowienia
    8. Dodaj numer przesylki do Allegro (POST /order/checkout-forms/{id}/shipments)
    """
```

### Dopasowanie delivery_service_id

Trzeba zbudowac mapowanie miedzy `delivery_method.name` z zamowienia a `deliveryServiceId`:

```python
# Przykladowe mapowanie (do uzupelnienia na podstawie GET /delivery-services)
DELIVERY_METHOD_MAP = {
    "Allegro Paczkomaty InPost 24/7": "inpost_locker",
    "Allegro Kurier DPD": "dpd_courier",
    "Allegro Kurier DHL": "dhl_courier",
    "Allegro One Box": "allegro_one_box",
    "Allegro One Punkt": "allegro_one_punkt",
    "Allegro Automat Orlen Paczka": "orlen_automat",
    # ... uzupelnic po wywolaniu GET /delivery-services
}
```

### Dane nadawcy (Retriever Shop)
Stale dane nadawcy zdefiniowac w settings_store lub .env:
```
SENDER_NAME=Retriever Shop
SENDER_STREET=...
SENDER_CITY=...
SENDER_ZIPCODE=...
SENDER_PHONE=...
SENDER_EMAIL=...
```

### Modyfikacja print_agent.py

`LabelAgent` traci metody `call_api()`, `get_orders()`, `get_order_packages()`, `get_label()`.
Zamiast nich uzywa `AllegroLabelService`:

```python
# Stary flow (BaseLinker):
# call_api("getOrders") -> call_api("getPackages") -> call_api("getLabel") -> print

# Nowy flow (Allegro):
# event -> create_shipment() -> get_shipment_label() -> print_label()
```

Petla glowna agenta zmienia sie na:
1. Sprawdz kolejke zamowien do druku (z bazy, nie z BaseLinker API)
2. Dla kazdego: `create_shipment()` -> poczekaj -> `get_shipment_label()` -> `print_label()`
3. Zapisz waybill, dodaj numer przesylki do Allegro

---

## 6. Faza 3 - Integracja wFirma (faktury)

### Cel
Automatyczne wystawianie faktur VAT w wFirma i wysylka PDF do Allegro + klienta.

### wFirma API

**Autoryzacja**: API Key (3 klucze: accessKey, secretKey, appKey)
- accessKey + secretKey: generowane w wFirma (Ustawienia >> Bezpieczenstwo >> Aplikacje >> Klucze API)
- appKey: uzyskiwany od wFirma przez formularz kontaktowy

**URL bazowe**: `https://api2.wfirma.pl`
**Format**: JSON (inputFormat=json&outputFormat=json)

### Implementacja: `wfirma_api/client.py`

```python
class WFirmaClient:
    BASE_URL = "https://api2.wfirma.pl"
    
    def __init__(self, access_key, secret_key, app_key, company_id=None):
        self.headers = {
            "accessKey": access_key,
            "secretKey": secret_key,
            "appKey": app_key,
            "Content-Type": "application/json",
        }
        self.company_id = company_id
    
    def _request(self, action, data=None):
        """POST do wFirma API z retry logic."""
        url = f"{self.BASE_URL}/{action}"
        params = {"inputFormat": "json", "outputFormat": "json"}
        if self.company_id:
            params["company_id"] = self.company_id
        # ... implementacja z retry
```

### Implementacja: `wfirma_api/invoices.py`

```python
def create_invoice(client, *, order, contractor_id=None):
    """
    POST /invoices/add
    
    Tworzy fakture VAT na podstawie zamowienia.
    
    Body (JSON):
    {
        "invoices": [{
            "invoice": {
                "paymentmethod": "transfer",
                "paymentdate": "2026-03-15",
                "date": "2026-03-15",
                "type": "normal",  # faktura VAT
                "contractor": {
                    "name": "Jan Kowalski",
                    "street": "ul. Testowa 1",
                    "zip": "00-001",
                    "city": "Warszawa",
                    "nip": "1234567890",  # jesli firma
                    "country": "PL"
                },
                "invoicecontents": [{
                    "invoicecontent": {
                        "name": "Szelki dla psa - rozmiar M",
                        "unit": "szt.",
                        "count": 1,
                        "price": 89.99,  # netto lub brutto
                        "vat": "23"
                    }
                }]
            }
        }]
    }
    
    Zwraca: invoice_id
    """

def download_invoice_pdf(client, invoice_id):
    """
    GET /invoices/download/{invoice_id}
    
    Zwraca binarny plik PDF faktury.
    """
```

### Flow fakturowania

```
1. Zamowienie oplacone (READY_FOR_PROCESSING)
2. Sprawdz czy klient chce fakture (want_invoice == True LUB invoice_nip niepusty)
3. Znajdz/utworz kontrahenta w wFirma (contractors/add lub find po NIP)
4. Utworz fakture (/invoices/add):
   - Dla firm: faktura VAT z NIP
   - Dla osob: faktura imienna (bez NIP)
5. Pobierz PDF (/invoices/download/{id})
6. Upload PDF do Allegro (POST /order/checkout-forms/{id}/invoices):
   a. Utworz obiekt faktury (POST .../invoices z nazwa pliku i numerem)
   b. Upload plik PDF (PUT .../invoices/{invoiceId}/file)
7. Zapisz invoice_id i numer faktury w bazie
```

### Nowe ustawienia w settings_store

```
WFIRMA_ACCESS_KEY=...
WFIRMA_SECRET_KEY=...
WFIRMA_APP_KEY=...
WFIRMA_COMPANY_ID=...
WFIRMA_INVOICE_SERIES_ID=...  # seria numeracji faktur
WFIRMA_DEFAULT_VAT=23
```

---

## 7. Faza 4 - Email do klienta

### Cel
Wysylac emaile transakcyjne do klientow na kazdym etapie realizacji zamowienia.

### Typy emaili

| Typ | Kiedy | Zawartosc |
|---|---|---|
| Potwierdzenie zamowienia | Po oplaceniu (READY_FOR_PROCESSING) | Podsumowanie zamowienia, produkty, kwota, metoda dostawy |
| Faktura | Po wystawieniu faktury | "Faktura nr FV/xxx w zalaczniku", PDF jako attachment |
| Informacja o wysylce | Po utworzeniu etykiety + waybill | Numer przesylki, link do sledzenia, przewoznik |
| Dostarczenie | Po statusie DELIVERED z tracking | "Przesylka dostarczona", prosba o opinie |
| Zwrot | Po wykryciu zwrotu | Potwierdzenie przyjecia zwrotu, info o refundzie |

### Implementacja: `services/email_service.py`

```python
class TransactionalEmailService:
    """
    Serwis do wysylki emaili transakcyjnych.
    Uzywa istniejacego SMTP z notifications/alerts.py.
    """
    
    def send_order_confirmation(self, order):
        """Email po oplaceniu zamowienia."""
    
    def send_invoice(self, order, invoice_pdf_bytes, invoice_number):
        """Email z faktura jako zalacznik PDF."""
    
    def send_shipment_notification(self, order, tracking_number, carrier_name, tracking_url):
        """Email o nadaniu przesylki z linkiem do sledzenia."""
    
    def send_delivery_confirmation(self, order):
        """Email po dostarczeniu przesylki."""
    
    def send_return_confirmation(self, return_record):
        """Email potwierdzajacy przyjecie zwrotu."""
```

### Szablony HTML

Katalog `magazyn/templates/emails/` z szablonami Jinja2:
- `order_confirmation.html`
- `invoice_email.html`
- `shipment_notification.html`
- `delivery_confirmation.html`
- `return_confirmation.html`
- `base_email.html` (layout bazowy z logo Retriever Shop)

### Konfiguracja SMTP

Istniejace ustawienia wystarczaja (SMTP_SERVER, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD).
Dodatkowe:
```
EMAIL_FROM_NAME=Retriever Shop
EMAIL_FROM_ADDRESS=sklep@retrievershop.pl
EMAIL_REPLY_TO=kontakt@retrievershop.pl
```

---

## 8. Faza 5 - Aktualizacja statusow Allegro

### Cel
Bezposrednio zarzadzac statusami realizacji w Allegro (fulfillment.status).

### Mapowanie wewnetrznych statusow na Allegro fulfillment

| Nasz status | Allegro fulfillment.status | Kiedy zmieniamy |
|---|---|---|
| pobrano | - | Nie zmieniamy (Allegro juz ma NEW) |
| wydrukowano | PROCESSING | Po wydrukowaniu etykiety |
| spakowano | READY_FOR_SHIPMENT | Po skanowaniu paczki |
| przekazano_kurierowi | SENT | Po nadaniu (waybill dostepny) |
| w_drodze | (nie zmieniamy) | Allegro trackuje samo |
| dostarczono | (nie zmieniamy) | Allegro trackuje samo |

### Implementacja: `allegro_api/fulfillment.py`

```python
def update_fulfillment_status(access_token, checkout_form_id, status, revision=None):
    """
    PUT /order/checkout-forms/{id}/fulfillment
    
    status: NEW, PROCESSING, READY_FOR_SHIPMENT, SENT, READY_FOR_PICKUP, PICKED_UP
    
    Opcjonalnie: checkoutForm.revision do optimistic locking
    (409 CONFLICT jesli zamowienie zmienione w miedzyczasie)
    """

def add_shipment_tracking(access_token, checkout_form_id, *, carrier_id, waybill, line_items=None):
    """
    POST /order/checkout-forms/{id}/shipments
    
    Dodaje numer przesylki do zamowienia.
    carrier_id: "DHL", "INPOST", "DPD", "POCZTA_POLSKA", "ALLEGRO", "OTHER"
    waybill: numer listu przewozowego
    """

def get_shipment_tracking_numbers(access_token, checkout_form_id):
    """
    GET /order/checkout-forms/{id}/shipments
    
    Zwraca liste przesylek przypisanych do zamowienia.
    """
```

### Automatyczne zmiany statusow

```
Pipeline:
1. Zamowienie oplacone -> pobrano (wewnetrznie) 
2. Druk etykiety -> wydrukowano + Allegro PROCESSING
3. Skanowanie paczki -> spakowano + Allegro READY_FOR_SHIPMENT
4. Nadanie kurierowi -> przekazano_kurierowi + Allegro SENT + dodaj waybill
5. Reszta (w_drodze, dostarczono) - z Allegro Tracking API (juz dziala)
```

---

## 9. Faza 6 - Sledzenie przesylek i maile po dostarczeniu

### Cel
Uzyc istniejacego `fetch_parcel_tracking()` z `allegro_api/tracking.py` + dodac automatyczne maile.

### Obecny stan
- `allegro_api/tracking.py` juz implementuje `fetch_parcel_tracking(token, carrier_id, waybills)`
- `order_sync_scheduler.py` juz ma `_sync_allegro_fulfillment()` ktory aktualizuje statusy

### Co trzeba dodac
1. Rozszerzenie `_sync_allegro_fulfillment()` o trigger emaili:
   - Po wykryciu statusu DELIVERED -> `send_delivery_confirmation(order)`
   - Po wykryciu statusu RETURNED -> `send_return_confirmation(return)`

2. Mapowanie statusow tracking na nasze:
```python
TRACKING_TO_INTERNAL = {
    "PENDING": "przekazano_kurierowi",
    "IN_TRANSIT": "w_drodze",
    "RELEASED_FOR_DELIVERY": "w_drodze",
    "AVAILABLE_FOR_PICKUP": "gotowe_do_odbioru",
    "NOTICE_LEFT": "gotowe_do_odbioru",  # awizo
    "DELIVERED": "dostarczono",
    "RETURNED": "zwrot",
    "ISSUE": "niedostarczono",
}
```

3. Usuniecie BaseLinker tracking z `agent/tracking.py` - caly `TrackingService` zalezy od
   BaseLinker `getCourierTracking`. Zastapic Allegro tracking.

### Carrier ID dla tracking

Z `GET /order/carriers` lub z odpowiedzi shipment management:
- ALLEGRO (dla One Box, One Punkt, i inne Allegro Delivery)
- INPOST
- DPD
- DHL
- POCZTA_POLSKA
- ORLEN_PACZKA

Trzeba zbudowac mapowanie `delivery_method.name` -> `carrierId` dla tracking API.

---

## 10. Faza 7 - Reczne zamowienia (OLX)

### Cel
Formularz do recznego tworzenia zamowien dla sprzedazy z OLX i innych kanalow (~1-2/mies.).

### Blueprint: `blueprints/manual_orders.py`

```python
@bp.route("/orders/manual/new", methods=["GET", "POST"])
def create_manual_order():
    """
    Formularz recznego zamowienia:
    
    Sekcja klienta:
    - Imie i nazwisko
    - Email, telefon
    - Adres dostawy (ulica, miasto, kod, kraj)
    - Opcjonalnie: punkt odbioru (paczkomat ID)
    
    Sekcja produktow:
    - Wyszukiwanie po nazwie/EAN/SKU (AJAX autocomplete z product_sizes)
    - Wybor produktu -> automatycznie wypelnia nazwe, cene, EAN
    - Mozliwosc recznego wpisania nazwy i ceny (dla produktow spoza bazy)
    - Ilosc
    - Przycisk "+" do dodania kolejnych pozycji
    
    Sekcja kosztow:
    - Automatyczna kalkulacja wartosci zamowienia
    - Koszt wysylki (reczny lub z tabeli)
    - Prowizja platformy (% lub kwota reczna)
    - Calkowity koszt sprzedazy
    
    Sekcja wysylki:
    - Metoda dostawy (dropdown: InPost Paczkomat, Kurier DPD, itp.)
    - Numer przesylki (opcjonalnie - mozna dodac pozniej)
    
    Sekcja faktury:
    - Checkbox: klient chce fakture
    - Nazwa firmy, NIP (warunkowe)
    
    Sekcja zrodla:
    - Platform: "olx", "manual", "other"
    - Notatki/komentarze
    """
```

### Flow recznego zamowienia

```
1. Uzytkownik wypelnia formularz
2. System tworzy Order z order_id = "manual_{uuid}" 
   - platform = "olx" / "manual"
   - external_order_id = None (brak Allegro)
3. Produkty dopasowane po EAN -> automatyczne odejmowanie stanu magazynowego
4. Kalkulacja kosztow (produkt netto/brutto, wysylka, prowizja)
5. Opcjonalnie: wystawienie faktury w wFirma (ten sam flow co Allegro)
6. Opcjonalnie: wyslanie emaila do klienta
7. Etykieta: reczny upload lub brak (sprzedaz osobista)
```

### Endpoint API (AJAX)

```python
@bp.route("/api/products/search", methods=["GET"])
def search_products():
    """
    Wyszukiwanie produktow dla autocomplete.
    Parametr: q (query)
    Szuka po: name, ean, sku w ProductSize
    Zwraca: [{id, name, ean, price, size, stock_quantity, location}]
    """
```

---

## 11. Zmiany w modelu danych

### Model Order - nowe pola

```python
class Order(Base):
    # ... istniejace pola ...
    
    # Nowe pola
    allegro_checkout_form_id = Column(String, nullable=True, index=True)  # UUID Allegro (duplikat external_order_id ale jawna nazwa)
    
    # Faktura
    wfirma_invoice_id = Column(Integer, nullable=True)  # ID faktury w wFirma
    invoice_number = Column(String, nullable=True)  # Nr faktury (np. "FV 12/03/2026")
    invoice_pdf_uploaded = Column(Boolean, default=False)  # Czy PDF uploadowany do Allegro
    
    # Przesylka (Wysylam z Allegro)
    shipment_id = Column(String, nullable=True)  # ID przesylki z Shipment Management API
    waybill = Column(String, nullable=True)  # Numer listu przewozowego (= delivery_package_nr)
    carrier_id = Column(String, nullable=True)  # ID przewoznika Allegro (INPOST, DPD, itp.)
    label_printed = Column(Boolean, default=False)  # Czy etykieta wydrukowana
    
    # Emaile wyslane
    email_confirmation_sent = Column(Boolean, default=False)
    email_invoice_sent = Column(Boolean, default=False)
    email_shipment_sent = Column(Boolean, default=False)
    email_delivery_sent = Column(Boolean, default=False)
    
    # Allegro event tracking
    last_allegro_event_id = Column(String, nullable=True)  # Ostatnie przetworzone zdarzenie
```

### Nowa tabela: allegro_event_cursor

```python
class AllegroEventCursor(Base):
    """Pozycja kursora w dzienniku zdarzen Allegro."""
    __tablename__ = "allegro_event_cursor"
    
    id = Column(Integer, primary_key=True, default=1)
    last_event_id = Column(String, nullable=True)  # ID ostatniego przetworzonego zdarzenia
    last_check_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
```

### Migracja bazy danych

Plik: `magazyn/migrations/replace_baselinker.py`

```python
def upgrade(db):
    """
    1. Dodaj nowe kolumny do orders
    2. Utworz tabele allegro_event_cursor
    3. Dla istniejacych zamowien: skopiuj external_order_id do allegro_checkout_form_id
    4. Dla zamowien z delivery_package_nr: skopiuj do waybill
    """
```

---

## 12. Pliki do modyfikacji / utworzenia

### Nowe pliki (w kolejnosci tworzenia)

| Nr | Plik | Faza | Opis |
|---|---|---|---|
| 1 | `magazyn/allegro_api/events.py` | F1 | Polling dziennika zdarzen |
| 2 | `magazyn/allegro_api/fulfillment.py` | F5 | Zmiana statusow + dodawanie numerow przesylek |
| 3 | `magazyn/allegro_api/shipment_management.py` | F2 | Tworzenie przesylek, etykiety |
| 4 | `magazyn/allegro_api/carriers.py` | F2 | Lista przewoznikow |
| 5 | `magazyn/allegro_api/invoices.py` | F3 | Upload faktur do Allegro |
| 6 | `magazyn/wfirma_api/__init__.py` | F3 | Pakiet wFirma |
| 7 | `magazyn/wfirma_api/client.py` | F3 | Klient HTTP wFirma |
| 8 | `magazyn/wfirma_api/invoices.py` | F3 | Tworzenie faktur |
| 9 | `magazyn/wfirma_api/contractors.py` | F3 | Kontrahenci |
| 10 | `magazyn/services/order_pipeline.py` | F1-F6 | Orkiestrator pipeline'u |
| 11 | `magazyn/services/email_service.py` | F4 | Emaile transakcyjne |
| 12 | `magazyn/services/label_service.py` | F2 | Serwis etykiet |
| 13 | `magazyn/blueprints/manual_orders.py` | F7 | Formularz recznych zamowien |
| 14 | `magazyn/templates/manual_order_form.html` | F7 | Szablon formularza |
| 15 | `magazyn/templates/emails/base_email.html` | F4 | Bazowy layout emaila |
| 16 | `magazyn/templates/emails/order_confirmation.html` | F4 | Potwierdzenie zamowienia |
| 17 | `magazyn/templates/emails/invoice_email.html` | F4 | Email z faktura |
| 18 | `magazyn/templates/emails/shipment_notification.html` | F4 | Informacja o wysylce |
| 19 | `magazyn/templates/emails/delivery_confirmation.html` | F4 | Potwierdzenie dostarczenia |
| 20 | `magazyn/migrations/replace_baselinker.py` | F1 | Migracja bazy danych |

### Modyfikacje istniejacych plikow

| Plik | Faza | Zakres zmian |
|---|---|---|
| `magazyn/orders.py` | F1 | Usuniecie `_sync_orders_from_baselinker()`, BASELINKER_STATUS_MAP, ALL_STATUS_IDS |
| `magazyn/order_sync_scheduler.py` | F1 | Nowa funkcja `_sync_from_allegro_events()`, zmiana interwalu na 60s |
| `magazyn/print_agent.py` | F2 | Wymiana `call_api()` na `AllegroLabelService`, usuniecie BaseLinker API |
| `magazyn/agent/tracking.py` | F6 | Usuniecie `TrackingService` (BaseLinker), nowy z Allegro tracking |
| `magazyn/returns.py` | F6 | Usuniecie `check_baselinker_order_returns()`, uzycie Allegro customer-returns |
| `magazyn/models.py` | F1 | Nowe pola Order, tabela AllegroEventCursor |
| `magazyn/settings_store.py` | F1-F3 | Nowe klucze (wFirma, email, sender) |
| `magazyn/env_info.py` | F1-F3 | Opisy nowych ustawien |
| `magazyn/diagnostics.py` | F1 | Usuniecie endpointu `/hooks/baselinker/label_failed` |
| `magazyn/allegro_api/__init__.py` | F1-F5 | Nowe importy (events, fulfillment, shipment_management, invoices, carriers) |
| `magazyn/config.py` | F3 | Proxy dla nowych ustawien wFirma |

---

## 13. Migracja danych

### Krok 1: Przygotowanie (przed wdrozeniem)
1. Eksport wszystkich zamowien BaseLinker (dla archiwum)
2. Sprawdzenie czy wszystkie zamowienia maja `external_order_id` (Allegro UUID)
3. Backup bazy SQLite

### Krok 2: Migracja schematu
1. Uruchom `replace_baselinker.py` - dodaje nowe kolumny
2. Kopiuj `external_order_id` -> `allegro_checkout_form_id`
3. Kopiuj `delivery_package_nr` -> `waybill`
4. Ustaw `carrier_id` na podstawie `courier_code`/`delivery_package_module`

### Krok 3: Inicjalizacja kursora eventow
1. Wywolaj `GET /order/event-stats` dla najnowszego event_id
2. Zapisz do `allegro_event_cursor` (zaczynamy od teraz, nie odtwarzamy historii)

### Krok 4: Weryfikacja
1. Porownaj liczbe zamowien w bazie z Allegro checkout-forms
2. Sprawdz czy statusy sie zgadzaja
3. Test: nowe zamowienie na Sandbox -> caly pipeline

---

## 14. Plan usuwania BaseLinker

### Strategia: Dual-run (rownolegly tryb)

**Etap A (2-4 tygodnie)**: Oba zrodla aktywne
- Nowy sync z Allegro Events: AKTYWNY (zapis do bazy)
- Stary sync z BaseLinker: AKTYWNY ale READ-ONLY (loguje roznice, nie nadpisuje)
- Porownanie: co godzine sprawdz czy oba zrodla daja te same zamowienia

**Etap B (1-2 tygodnie)**: Allegro primary
- Allegro Events: jedyne zrodlo zapisu
- BaseLinker: wylaczony sync, pozostaje tylko dostep do historycznych danych
- Etykiety: przez Wysylam z Allegro (nie BaseLinker)

**Etap C**: Pelne odciecie
- Usuniecie kodu BaseLinker
- Usuniecie API_TOKEN, BASELINKER_WEBHOOK_TOKEN z settings
- Rezygnacja z planu BaseLinker (oszczednosc kosztow)

### Kolejnosc wdrazania faz

```
Tydzien 1-2: Faza 1 (Events) + Faza 5 (statusy) - fundament
Tydzien 3-4: Faza 2 (etykiety) - zastepuje najwazniejsza funkcje BaseLinker
Tydzien 5-6: Faza 3 (wFirma) + Faza 4 (emaile)
Tydzien 7:   Faza 6 (tracking upgrade) + Faza 7 (reczne zamowienia)
Tydzien 8:   Etap C - pelne odciecie BaseLinker
```

---

## 15. Zaleznosci zewnetrzne

### Do uzyskania przed rozpoczeciem

| Element | Status | Akcja |
|---|---|---|
| Allegro OAuth token | GOTOWE | Juz skonfigurowane w settings_store |
| Allegro Shipment Management dostep | DO SPRAWDZENIA | Sprawdzic czy konto ma aktywna usluge "Wysylam z Allegro" |
| wFirma appKey | DO UZYSKANIA | Wypelnic formularz na wfirma.pl/kontakt |
| wFirma accessKey + secretKey | DO WYGENEROWANIA | Ustawienia >> Bezpieczenstwo >> Klucze API |
| SMTP (istniejacy) | DO SPRAWDZENIA | Sprawdzic czy SMTP_SERVER juz skonfigurowany |
| Dane nadawcy | DO WPISANIA | Adres Retriever Shop do etykiet |

### Wymagania Allegro API
- OAuth2 z `order:read`, `order:write` scope
- Dodatkowo scope dla Shipment Management (sprawdzic dokumentacje)
- Rate limiting: respektowac `X-RateLimit-Remaining` (juz zaimplementowane w `core.py`)

---

## 16. Ryzyka i mitygacja

| Ryzyko | Prawdopodobienstwo | Wplyw | Mitygacja |
|---|---|---|---|
| Allegro Events API ma opoznienia | Srednie | Sredni | Fallback na polling checkout-forms co 5 min |
| Shipment Management niedostepne dla konta | Niskie | Wysoki | Sprawdzic przed rozpoczeciem; alternatywa: reczne etykiety u przewoznikow |
| wFirma API limit requestow | Niskie | Niski | Kolejkowanie faktur, wykonywanie w nocy |
| Utrata danych przy migracji | Niskie | Wysoki | Pelny backup przed kazda zmiana, dual-run |
| Klient anuluje po READY_FOR_PROCESSING | Srednie | Niski | Obsluga eventu BUYER_CANCELLED -> anulowanie w pipeline |
| Email do spamu | Srednie | Sredni | Konfiguracja SPF/DKIM/DMARC dla domeny |
| Zmiana API Allegro | Niskie | Sredni | Wersjonowanie headerow (vnd.allegro.public.v1+json) |

---

## Podsumowanie pipeline'u docelowego

```
[Klient kupuje na Allegro]
         |
         v
[Allegro Event: READY_FOR_PROCESSING]
         |
         v
[order_sync_scheduler -> _sync_from_allegro_events()]
    - Pobiera szczegoly z checkout-forms
    - Tworzy Order w bazie
    - Status: "pobrano"
         |
         v
[order_pipeline.py - orkiestrator]
    |
    +-- 1. Faktura (wFirma)
    |      - Utworz kontrahenta
    |      - Wystaw fakture VAT
    |      - Pobierz PDF
    |      - Upload do Allegro
    |
    +-- 2. Email: potwierdzenie zamowienia
    |
    +-- 3. Etykieta (Wysylam z Allegro)
    |      - create_shipment()
    |      - get_shipment_label()
    |      - print_label() (CUPS)
    |      - Status: "wydrukowano"
    |      - Allegro: PROCESSING
    |
    +-- 4. Email: faktura (PDF w zalaczniku)
    |
    +-- 5. [Skanowanie paczki - reczne]
    |      - Status: "spakowano"
    |      - Allegro: READY_FOR_SHIPMENT
    |
    +-- 6. [Nadanie - automatyczne po waybill]
    |      - Dodaj waybill do Allegro
    |      - Status: "przekazano_kurierowi"
    |      - Allegro: SENT
    |
    +-- 7. Email: informacja o wysylce + link sledzenia
         |
         v
[Tracking scheduler (co 15 min)]
    - GET /order/carriers/{carrierId}/tracking
    - Aktualizacja statusow (w_drodze, gotowe_do_odbioru, dostarczono)
    - Przy DELIVERED -> email do klienta
    - Przy RETURNED -> email + utworz Return
         |
         v
[Zamowienie zakonczone]
```
