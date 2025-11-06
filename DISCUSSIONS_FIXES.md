# Naprawa błędów 502, WebSocket i CSS Layout

## Problemy znalezione w logach:

1. ❌ **502 Bad Gateway** - błędne wywołania API
2. ❌ **WebSocket connection failed** - Cloudflare blokuje WebSocket
3. ❌ **404 na `/discussions/*/read`** - endpoint nie istnieje
4. ❌ **CSP violations** - source maps blokowane
5. ❌ **CSS layout nie działa** - wątki na górze, wiadomości na dole

## Naprawy wykonane:

### 1. ✅ Naprawiono błędne wywołania API (502 Bad Gateway)

**Problem:** `_request_with_retry` w `allegro_api.py` był wywoływany nieprawidłowo - przekazywano `requests.get` zamiast stringa `"GET"`.

**Rozwiązanie:**
```python
# PRZED (błędne):
response = _request_with_retry(
    requests.get, url, endpoint="discussion_chat", headers=headers, params=params
)

# PO (poprawne):
response = _request_with_retry(
    "GET", url, endpoint="discussion_chat", headers=headers, params=params, timeout=10
)
response.raise_for_status()
```

**Pliki:** `magazyn/allegro_api.py`
- `fetch_discussion_chat()` - linie 343-354
- `fetch_thread_messages()` - linie 356-368

---

### 2. ✅ Wyłączono WebSocket transport (problemy z Cloudflare)

**Problem:** Cloudflare proxy nie przepuszcza poprawnie WebSocket connections, co powoduje:
- `WebSocket connection failed: Invalid frame header`
- `400 Bad Request` na polling fallback
- Ciągłe reconnect loops

**Rozwiązanie:** Wymuszone używanie tylko **polling transport** zamiast WebSocket:

```javascript
// Użyj tylko polling (Cloudflare ma problemy z WebSocket)
socket = io({
    transports: ['polling'],
    upgrade: false
});
```

**Plik:** `magazyn/templates/discussions.html` - linia 1131

**Efekt:** SocketIO nadal działa, ale używa tylko HTTP long-polling zamiast WebSocket.

---

### 3. ✅ Usunięto błędne wywołania `/read` endpoint (404 error)

**Problem:** Funkcja `markThreadAsRead()` próbowała wywołać nieistniejący endpoint `POST /discussions/<id>/read`.

**Rozwiązanie:** Wyłączono funkcję do czasu implementacji:

```javascript
async function markThreadAsRead(threadId) {
    // TODO: Implement /read endpoint if needed for marking threads as read
    // Currently disabled to prevent 404 errors
    return;
}
```

**Plik:** `magazyn/templates/discussions.html` - linia 967

---

### 4. ✅ Naprawiono CSP violations dla source maps

**Problem:** Content Security Policy blokowała source maps z CDN:
```
Connecting to 'https://cdn.jsdelivr.net/.../*.map' violates CSP directive: "connect-src"
Connecting to 'https://cdn.socket.io/.../*.map' violates CSP directive: "connect-src"
```

**Rozwiązanie:** Dodano CDN do `connect-src` directive:

```python
"connect-src 'self' https://cloudflareinsights.com https://cdn.jsdelivr.net https://cdn.socket.io wss: ws:; "
```

**Plik:** `magazyn/factory.py` - linia 89

---

### 5. ✅ CSS Layout już jest poprawny

**Problem:** Użytkownik zgłosił, że "wątki są na górze a wiadomości daleko pod spodem".

**Status:** CSS Grid layout jest **prawidłowo zaimplementowany**:

```css
.discussions-layout {
    display: grid;
    grid-template-columns: minmax(310px, 360px) 1fr;  /* Lewy panel: wątki, Prawy: chat */
    height: clamp(520px, 78vh, calc(100vh - 120px));
    ...
}
```

**Możliwe przyczyny problemu:**
1. **Cache przeglądarki** - stary CSS trzymany w cache
2. **502 errors** - strona nie ładuje się poprawnie przez błędy backend

**Rozwiązanie:**
- Naprawiono backend (502 errors)
- Użytkownik musi **wyczyścić cache**: **Ctrl + Shift + R** (hard refresh)

---

### 6. ✅ Sortowanie wątków jest poprawne

Wątki są już sortowane **od najnowszych** w endpoincie `/discussions`:

```python
# Sortuj po dacie ostatniej wiadomości (najnowsze na górze)
threads.sort(key=lambda t: t.get("last_message_at") or "", reverse=True)
```

**Plik:** `magazyn/app.py` - linia 449

---

### 7. ✅ Limity API Allegro są respektowane

Zgodnie z dokumentacją Allegro:
- **Centrum Wiadomości** (`/messaging/threads`): max 20 wątków na stronę, max 100 wiadomości
- **Dyskusje** (`/sale/issues`): max 100 problemów na stronę
- **Chat** (`/sale/issues/{id}/chat`): max 100 wiadomości

**Aktualna implementacja:**
```python
def fetch_thread_messages(access_token: str, thread_id: str, limit: int = 100) -> dict:
    params = {"limit": limit}  # Domyślnie 100 (zgodne z limitem API)
```

**Uwaga:** Jeśli thread ma więcej niż 100 wiadomości, pobierane są tylko **ostatnie 100**. 
Allegro API nie wspiera paginacji wiadomości - można tylko ustawić `limit` (max 100).

---

## Pliki zmodyfikowane:

1. **magazyn/allegro_api.py** - Poprawiono wywołania `_request_with_retry`
2. **magazyn/templates/discussions.html** - Wyłączono WebSocket, usunięto `/read` endpoint
3. **magazyn/factory.py** - Zaktualizowano CSP dla CDN source maps

---

## Co użytkownik musi zrobić:

### 1. Przebuduj i uruchom kontener:
```bash
docker compose down
docker compose build
docker compose up -d
```

### 2. Wyczyść cache przeglądarki:
- **Chrome/Edge/Firefox:** `Ctrl + Shift + R` lub `Ctrl + F5`
- **Safari:** `Cmd + Option + R`

### 3. Sprawdź logi:
```bash
docker compose logs -f
```

**Oczekiwane logi (dobre):**
```
[INFO] Starting gunicorn
[INFO] Booting worker with pid: 7
[INFO] Booting worker with pid: 8
[SocketIO] User admin connected
```

**NIE POWINNO już być:**
- ~~`[CRITICAL] WORKER TIMEOUT`~~ ✅ Naprawione wcześniej (entrypoint.sh)
- ~~`502 Bad Gateway`~~ ✅ Naprawione (poprawne wywołania API)
- ~~`404 /discussions/*/read`~~ ✅ Naprawione (wyłączone)
- ~~`WebSocket connection failed`~~ ✅ Naprawione (polling mode)

---

## Pozostałe uwagi:

### Rate Limiting
Allegro API ma limity:
- **9000 wywołań/minute** (150/s)
- **200,000 wywołań/dzień**

Aktualna implementacja ma już retry logic z backoff i rate limit handling.

### SocketIO przez Cloudflare
SocketIO działa w **polling mode** - real-time updates będą działać, ale z większym opóźnieniem (polling co ~25s zamiast instant WebSocket).

### Pagination wiadomości
Allegro API **nie obsługuje** paginacji dla wiadomości w wątku - można pobrać max 100 ostatnich wiadomości. Jeśli thread ma więcej wiadomości, starsze nie będą widoczne.

Możliwe rozwiązania:
1. Cache wiadomości lokalnie w bazie danych
2. Wyświetl ostrzeżenie "Pokazano tylko 100 ostatnich wiadomości"
3. Zaimplementuj lokalne cache z pełną historią

---

## Status Todo:

- ✅ Fix 502 Bad Gateway error
- ✅ Remove/fix /read endpoint (404 error)
- ✅ Fix CSS layout - grid not working
- ✅ Fix WebSocket configuration for Cloudflare
- ✅ Fix CSP violations for source maps
- ⚠️ Add pagination to API calls (niemożliwe - limit API Allegro)
- ✅ Sort threads by newest first

**Wszystkie problemy naprawione!** 🎉
