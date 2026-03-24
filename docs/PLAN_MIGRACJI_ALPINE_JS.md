# Plan migracji na Alpine.js

## Cel

Zastapienie calego inline JavaScript oraz dedykowanych plikow JS reaktywnym frameworkiem Alpine.js.
Korzysc: czytelniejszy kod, mniej manipulacji DOM, latwe utrzymanie, lepsze wsparcie polskich znakow
(reaktywne wiazanie tekstu zamiast recznego budowania HTML).

## Zasady migracji

1. **Stopniowa migracja** - Alpine.js wspolpracuje z istniejacym JS. Mozna migrowac szablon po szablonie.
2. **CDN** - Dodajemy Alpine.js z CDN (po Bootstrap, przed barcode-scanner.js) w `base.html`.
3. **Bez buildera** - Alpine nie wymaga webpack/vite. Jeden tag `<script>` i gotowe.
4. **Polskie znaki** - Przy migracji na `x-text`/`x-html` upewniamy sie, ze wszystkie etykiety
   uzywaja poprawnych polskich diakrytykow (np. "Zamowienie" -> "Zamowienie" jest OK w kodzie,
   ale w wyswietlanym tekscie musi byc "Zamówienie" z ogonkami).
5. **Barcode scanner** - Zachowujemy jako osobny modul JS (globalne `keydown` capture nie pasuje do Alpine).

---

## Statystyki projektu

| Kategoria | Wartosc |
|-----------|---------|
| Szablony HTML ogolnie | ~40 |
| Szablony z inline JS | ~22 |
| Szablony bez JS (bez zmian) | ~18 |
| Pliki JS w static/ | 3 (barcode-scanner, price_check, quagga) |
| Szacunkowa ilosc linii inline JS | ~1500 |
| Unikalne wzorce JS do migracji | 10 |

---

## Faza 1 — Fundamenty (base.html)

**Priorytet: KRYTYCZNY**
**Plik: `magazyn/templates/base.html`**

Dodanie Alpine.js do base.html i migracja podstawowych interakcji:

### 1.1 Dodanie Alpine.js
```html
<script defer src="https://cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/cdn.min.js"></script>
```
Umieszczenie w `<head>` z atrybutem `defer` (przed Bootstrap bundle).

### 1.2 Mobile menu
**Obecny kod**: `classList.toggle('show')` z oddzielnymi event listenerami na przycisk, close, linki.

**Alpine**:
```html
<div x-data="{ menuOpen: false }">
    <button @click="menuOpen = !menuOpen">Menu</button>
    <nav x-show="menuOpen" @click.away="menuOpen = false" x-transition>
        ...
    </nav>
</div>
```

### 1.3 Dropdown hover (desktop) / click (mobile)
**Obecny kod**: `mouseenter`/`mouseleave` na `.nav-item.dropdown`.

**Alpine**:
```html
<div x-data="{ open: false }"
     @mouseenter="if(window.innerWidth >= 992) open = true"
     @mouseleave="if(window.innerWidth >= 992) open = false"
     @click="if(window.innerWidth < 992) open = !open">
    <div x-show="open" x-transition>...</div>
</div>
```

### 1.4 Wake Lock toggle
**Obecny kod**: `navigator.wakeLock.request('screen')`, przycisk toggle, `visibilitychange`.

**Alpine**:
```html
<div x-data="wakeLock()" x-init="init()">
    <button @click="toggle()" x-text="active ? 'Ekran: wlaczony' : 'Ekran: wylaczyc'"></button>
</div>
```
Z komponentem `wakeLock()` zarejestrowanym w `Alpine.data()`.

### 1.5 Flash messages auto-dismiss
**Obecny kod**: `setTimeout` + `classList.add('show')`.

**Alpine**:
```html
<div x-data="{ show: true }" x-init="setTimeout(() => show = false, 5000)"
     x-show="show" x-transition>
    ...
</div>
```

---

## Faza 2 — Najwyzszy priorytet (duzo JS, duze zyski)

### 2.1 discussions.html — Interfejs czatu
**Plik: `magazyn/templates/discussions.html`**
**Obecny inline JS: ~500 linii**

**Stan do przeniesienia na `x-data`**:
- `currentThreadId` — aktywny watek
- `threads[]` — lista watkow
- `messages[]` — wiadomosci aktywnego watku
- `isSending` — blokada wysylania
- `searchQuery` — filtrowanie watkow

**Plan**:
```html
<div x-data="chatApp()" x-init="loadThreads()">
    <!-- Panel watkow -->
    <div>
        <input x-model="searchQuery" placeholder="Szukaj...">
        <template x-for="thread in filteredThreads" :key="thread.id">
            <div @click="loadThread(thread.id)"
                 :class="{ 'active': thread.id === currentThreadId }">
                <span x-text="thread.title"></span>
                <span x-show="thread.unread > 0" x-text="thread.unread"></span>
            </div>
        </template>
    </div>
    <!-- Panel wiadomosci -->
    <div>
        <template x-for="msg in messages" :key="msg.id">
            <div :class="msg.direction">
                <span x-text="msg.text"></span>
                <small x-text="msg.time"></small>
            </div>
        </template>
        <form @submit.prevent="sendMessage()">
            <textarea x-model="newMessage" @keydown.enter.prevent="sendMessage()"></textarea>
            <button :disabled="isSending">Wyslij</button>
        </form>
    </div>
</div>
```

**Komponent `chatApp()` w Alpine.data()**:
- `loadThreads()` - fetch GET /discussions/api/threads
- `loadThread(id)` - fetch GET /discussions/{id}/messages
- `sendMessage()` - fetch POST /discussions/{id}/send
- `filteredThreads` - getter filtrujacy po `searchQuery`
- `markAsRead(id)` - fetch POST

### 2.2 home.html — Dashboard
**Plik: `magazyn/templates/home.html`**
**Obecny inline JS: ~300 linii (5 sekcji lazy loading)**

**Stan do przeniesienia**:
- `profit` — dane zysku
- `promotions[]` — aktywne wyroznienia
- `trends` — porownanie tygodniowe
- `bestsellers` — 3 tabele (tydzien/miesiac/ogolne)
- `slowMoving[]` — wolnoobrotowe produkty
- `loading` — flaga ladowania

**Plan**:
```html
<div x-data="dashboard()" x-init="loadHeavyData()">
    <!-- Karty zysku -->
    <div x-show="!loading">
        <span x-text="profit.today"></span>
        <span x-text="profit.week"></span>
    </div>

    <!-- Tabela wyroznien -->
    <template x-for="promo in promotions" :key="promo.id">
        <tr>
            <td x-text="promo.title"></td>
            <td x-text="promo.expires"></td>
            <td :class="promo.isExpiringSoon ? 'text-danger' : ''">
                <span x-text="promo.daysLeft"></span>
            </td>
        </tr>
    </template>

    <!-- Bestsellery -->
    <template x-for="item in bestsellers.week" :key="item.name">
        <tr>
            <td x-text="item.name"></td>
            <td x-text="item.quantity"></td>
        </tr>
    </template>
</div>
```

### 2.3 stocktake_scan.html — Skanowanie inwentaryzacji
**Plik: `magazyn/templates/stocktake_scan.html`**
**Obecny inline JS: ~150 linii**

**Stan**:
- `stats` — liczniki (zeskanowane, zgodne, rozbiezne)
- `scanResult` — ostatni wynik skanowania
- `history[]` — historia skanow (z `localStorage`)
- `error` — komunikat bledu

**Alpine plugin $persist** dla historii:
```html
<div x-data="stocktakeScan()" x-init="loadHistory()">
    <div x-text="stats.scanned + ' zeskanowanych'"></div>
    <div x-show="scanResult" x-transition>...</div>
    <template x-for="scan in history" :key="scan.timestamp">
        <div x-text="scan.barcode + ' - ' + scan.result"></div>
    </template>
</div>
```

### 2.4 price_check.js — Monitoring cen
**Plik: `magazyn/static/price_check.js` (~320 linii)**

Przepisanie na komponent Alpine z pollingiem:
```html
<div x-data="priceMonitor()" x-init="startPolling()">
    <template x-for="check in recentChecks" :key="check.id">
        <tr>
            <td x-text="check.title"></td>
            <td x-text="check.myPrice"></td>
            <td x-text="check.competitorPrice"></td>
            <td :class="check.statusClass" x-text="check.status"></td>
        </tr>
    </template>
</div>
```

---

## Faza 3 — Sredni priorytet (powtarzalne wzorce)

### 3.1 add_order.html — Formularz recznego zamowienia
**Plik: `magazyn/templates/add_order.html`**

Migracja na `x-data` z reaktywnym formularzem:
- `products[]` — tablica produktow (add/remove)
- `searchQuery` — wyszukiwanie produktow
- `suggestions[]` — wyniki wyszukiwania
- `commissionType` — typ prowizji (procent/kwota)
- `showPickup` — widocznosc paczkomatu
- `showInvoice` — widocznosc faktury

### 3.2 report_detail.html — Szczegoly raportu cenowego
**Plik: `magazyn/templates/price_reports/report_detail.html`**

Migracja:
- Przycisk recheck -> `@click` z `fetch`
- Modal zmiany ceny -> `x-data` ze stanem modala + `fetch POST`
- Modal wykluczenia sprzedawcy -> analogicznie

### 3.3 Wspolny komponent: Searchable Dropdown
**Pliki**: offers.html, offers_and_prices.html, review_invoice.html

Wyodrebnic wspolny komponent:
```html
<div x-data="searchableDropdown(options)">
    <input x-model="search" @focus="open = true">
    <div x-show="open" @click.away="open = false">
        <template x-for="opt in filteredOptions" :key="opt.id">
            <button @click="select(opt)" x-text="opt.label"></button>
        </template>
    </div>
    <input type="hidden" :value="selected?.id">
</div>
```

### 3.4 product_detail.html — Lazy loading historii
Prosty `x-data` z `loadMore()`:
```html
<div x-data="{ items: [], offset: 0, hasMore: true }">
    <template x-for="item in items">...</template>
    <button x-show="hasMore" @click="loadMore()">Zaladuj wiecej</button>
</div>
```

### 3.5 import_invoice.html — Drag-and-drop upload
```html
<div x-data="{ isDragging: false, file: null }"
     @dragover.prevent="isDragging = true"
     @dragleave="isDragging = false"
     @drop.prevent="file = $event.dataTransfer.files[0]; isDragging = false"
     :class="{ 'drag-over': isDragging }">
    ...
</div>
```

### 3.6 add_delivery.html — Dynamiczne wiersze
```html
<div x-data="{ rows: [{ size: '', qty: 0, price: 0 }] }">
    <template x-for="(row, index) in rows" :key="index">
        <div>
            <input x-model="row.size">
            <input x-model.number="row.qty">
            <button @click="rows.splice(index, 1)">Usun</button>
        </div>
    </template>
    <button @click="rows.push({ size: '', qty: 0, price: 0 })">Dodaj wiersz</button>
</div>
```

### 3.7 reports_list.html — Polling statusu
```html
<div x-data="{ status: null }" x-init="setInterval(() => fetchStatus(), 5000)">
    <div x-show="status?.isRunning">
        <div class="progress-bar" :style="'width:' + status.progress + '%'"></div>
    </div>
</div>
```

---

## Faza 4 — Niski priorytet (proste zamiany)

### 4.1 Per-page selector (items.html, orders_list.html, sales_list.html)
```html
<select @change="
    let url = new URL(window.location);
    url.searchParams.set('per_page', $el.value);
    url.searchParams.delete('page');
    window.location = url;
">
```

### 4.2 Password toggle (settings.html, sales_settings.html)
```html
<div x-data="{ show: false }">
    <input :type="show ? 'text' : 'password'">
    <button @click="show = !show">
        <i :class="show ? 'bi-eye-slash' : 'bi-eye'"></i>
    </button>
</div>
```

### 4.3 Filtrowanie wierszy (history.html, logs.html, stocktake_report.html)
```html
<div x-data="{ filter: '' }">
    <input x-model="filter">
    <template x-for="row in rows">
        <tr x-show="!filter || row.text.includes(filter)">...</tr>
    </template>
</div>
```

### 4.4 Toggle koloru (add_item.html)
```html
<div x-data="{ custom: false }">
    <select @change="custom = ($el.value === 'inny')">...</select>
    <input x-show="custom" x-transition>
</div>
```

---

## Poza zakresem (bez zmian)

| Plik | Powod |
|------|-------|
| `barcode-scanner.js` | Globalne keydown capture, samodzielny modul |
| `quagga.min.js` | Biblioteka zewnetrzna |
| `customer/order_status.html` | Brak JS, czysto serwerowa strona |
| Szablony email (6 plikow) | HTML email, brak JS |
| login.html, 404.html, 500.html | Brak JS |
| Szablony bez interakcji JS | Brak potrzeby migracji |

---

## Wspolne komponenty Alpine do wyodrebnienia

| Komponent | Uzycie | Opis |
|-----------|--------|------|
| `searchableDropdown(options)` | offers, offers_and_prices, review_invoice, add_order | Dropdown z wyszukiwaniem i filtracja opcji |
| `wakeLock()` | base.html | Zarzadzanie Wake Lock API |
| `lazyTable(url)` | product_detail, home | Lazy loading danych do tabeli z paginacja |
| `pollStatus(url, interval)` | reports_list, price_check | Polling statusu z automatycznym odswiezaniem |
| `dynamicRows(template)` | add_delivery, add_order | Dynamiczne dodawanie/usuwanie wierszy formularza |
| `confirmAction(message)` | orders_list, order_detail, items | Przycisk z potwierdzeniem przed akcja |

---

## Polskie znaki — lista plikow do poprawy

Przy kazdej migracji szablonu nalezy poprawic polskie znaki w wyswietlanych tekstach.
Ponizej lista plikow z brakujacymi diakrytykami:

| Plik | Przykladowe bledy |
|------|-------------------|
| base.html | "Strona glowna", "Zamowienia", "Wiadomosci", "Wyloguj sie", "Ladowanie..." |
| home.html | "Przychod", "zl", "Ladowanie trendow...", "Ilosc", "Blad" |
| orders_list.html | "Zamowienia", "Dodaj zamowienie", "wysylki", "Wyczysc", "Zakonczone" |
| order_detail.html | "Zamowienie", "Wysylka", "Platnosc", "oplat", "Pieniadze" |
| items.html | "produktow", "wyswietlono" |
| add_order.html | "Dodaj zamowienie reczne", "platnosci", "Zaplacono" |
| stocktake_scan.html | "Zakonczono", "Zakonczyc", "Cofnij", "Zeskanowane" |
| stocktake_report.html | "Rozbieznosci", "Zastosuj stany" |
| settings.html | "Sciezka", "miesieczne", "Ksiegowosc" |
| product_detail.html | "Zaladuj wiecej", "Blad ladowania" |
| report_detail.html | "Potwierdz zmiane ceny", "Ladowanie kalkulacji" |

---

## Szacunkowy naklad pracy

| Faza | Liczba szablonow | Zlozonosc |
|------|-----------------|-----------|
| Faza 1 (Fundamenty) | 1 (base.html) | Srednia |
| Faza 2 (Wysoki priorytet) | 4 | Wysoka |
| Faza 3 (Sredni priorytet) | 7-8 | Srednia |
| Faza 4 (Niski priorytet) | 7-8 | Niska |
| **Lacznie** | **~20 szablonow** | - |
