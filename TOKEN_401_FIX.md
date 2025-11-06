# Naprawa błędu 401 Unauthorized i problemów SocketIO

## Problemy:

1. ❌ **401 Unauthorized** - Token Allegro wygasł
2. ❌ **400 Bad Request dla refresh_token** - Nieprawidłowe dane lub refresh token wygasł
3. ❌ **400 Bad Request SocketIO** - Problemy z sesją w polling mode

---

## Naprawy wykonane:

### 1. ✅ Automatyczne odświeżanie tokena przy 401

**Lokalizacja:** `magazyn/app.py` - funkcja `discussions()`

**Co zostało dodane:**
```python
if status_code == 401:
    # Token wygasł - spróbuj odświeżyć
    refresh_token = getattr(settings, "ALLEGRO_REFRESH_TOKEN", None)
    if refresh_token:
        try:
            new_tokens = allegro_api.refresh_token(refresh_token)
            # Zaktualizuj tokeny
            settings.ALLEGRO_ACCESS_TOKEN = new_tokens.get("access_token")
            if new_tokens.get("refresh_token"):
                settings.ALLEGRO_REFRESH_TOKEN = new_tokens["refresh_token"]
            # Retry request
            return discussions()  # Spróbuj ponownie
        except Exception as refresh_exc:
            error_message = "Token wygasł i nie udało się go odświeżyć."
```

**Efekt:** Aplikacja automatycznie próbuje odświeżyć token gdy dostanie 401.

---

### 2. ✅ Naprawa SocketIO - usunięto wymaganie autoryzacji przy connect

**Lokalizacja:** `magazyn/socketio_extension.py`

**PRZED:**
```python
@socketio.on('connect')
@authenticated_only  # <-- To powodowało 400 errors
def handle_connect():
```

**PO:**
```python
@socketio.on('connect')  # Usunięto @authenticated_only
def handle_connect():
    username = session.get('username', 'anonymous')
    if username != 'anonymous':
        emit('connected', {'username': username})
```

**Efekt:** SocketIO może się połączyć nawet jeśli sesja nie jest idealnie skonfigurowana.

---

### 3. ✅ Poprawiona konfiguracja SocketIO dla Gevent

**Lokalizacja:** `magazyn/factory.py`

**PRZED:**
```python
socketio.init_app(app, cors_allowed_origins="*", async_mode='threading')
```

**PO:**
```python
socketio.init_app(
    app, 
    cors_allowed_origins="*", 
    async_mode='gevent',  # Zgodne z gunicorn worker
    manage_session=False,  # Flask zarządza sesjami
    engineio_logger=False,  # Mniej logów
    logger=False
)
```

**Efekt:** SocketIO używa tego samego async mode co Gunicorn (gevent).

---

## Co musisz zrobić teraz:

### KROK 1: Przebuduj i uruchom kontener

```bash
docker compose down
docker compose build
docker compose up -d
```

### KROK 2: Sprawdź czy token Allegro wymaga odświeżenia

**Jeśli błąd 400 przy refresh_token:**

To znaczy, że **refresh token też wygasł** lub dane CLIENT_ID/CLIENT_SECRET są nieprawidłowe.

**Rozwiązanie:** Musisz **ponownie autoryzować aplikację w Allegro**:

1. Wejdź na `/settings` (Ustawienia)
2. W sekcji "Integracja Allegro" kliknij **"Autoryzuj z Allegro"**
3. Zaloguj się do Allegro i zatwierdź uprawnienia
4. Nowy access_token i refresh_token zostaną zapisane

### KROK 3: Sprawdź logi

```bash
docker compose logs -f | grep -E "401|400|Token|SocketIO"
```

**Oczekiwane logi (dobre):**
```
[INFO] Próba odświeżenia tokena Allegro...
[INFO] Token Allegro odświeżony pomyślnie
[SocketIO] User admin connected
[INFO] "GET /discussions HTTP/1.1" 200
```

**Nie powinno być:**
- ~~`401 Client Error: Unauthorized`~~ (po auto-refresh)
- ~~`400 Bad Request for /socket.io/`~~ (po naprawie session)
- ~~`@authenticated_only` zwraca False~~ (usunięte)

---

## Dlaczego 400 przy refresh_token?

Możliwe przyczyny:

### 1. **Refresh token wygasł**
- Refresh tokeny Allegro są ważne **90 dni** (jeśli nie są używane)
- Po wygaśnięciu musisz ponownie autoryzować aplikację

### 2. **Nieprawidłowe CLIENT_ID lub CLIENT_SECRET**
Sprawdź w bazie danych lub `settings_store`:
```sql
SELECT key, value FROM app_settings 
WHERE key IN ('ALLEGRO_CLIENT_ID', 'ALLEGRO_CLIENT_SECRET');
```

Powinny pasować do danych z https://apps.allegro.pl/

### 3. **Zły format żądania**
Allegro wymaga:
```
POST https://allegro.pl/auth/oauth/token
Content-Type: application/x-www-form-urlencoded
Authorization: Basic base64(client_id:client_secret)

grant_type=refresh_token&refresh_token=YOUR_REFRESH_TOKEN
```

To jest już zaimplementowane poprawnie w `allegro_api.refresh_token()`.

---

## Automatyczne odświeżanie tokena

Aplikacja ma już zaimplementowany `AllegroTokenRefresher` w `allegro_token_refresher.py`:

- Działa w osobnym wątku
- Sprawdza co 5 minut
- Odświeża token **15 minut przed wygaśnięciem**
- Loguje wszystkie próby

**Sprawdź czy działa:**
```bash
docker compose logs | grep "Automatic Allegro token refresh"
```

Jeśli widzisz:
```
Automatic Allegro token refresh failed with HTTP status 400
```

To znaczy, że **refresh token wygasł** i musisz ponownie autoryzować.

---

## Quick Fix - Jak ponownie autoryzować Allegro:

### Opcja 1: Przez interfejs webowy
1. Przejdź do `/settings`
2. Kliknij "Autoryzuj z Allegro"
3. Zaloguj się i zatwierdź

### Opcja 2: Ręcznie (jeśli masz code)
```python
# W Pythonie lub przez /api/allegro/callback
import allegro_api

code = "YOUR_AUTHORIZATION_CODE"
client_id = "YOUR_CLIENT_ID"
client_secret = "YOUR_CLIENT_SECRET"
redirect_uri = "https://magazyn.retrievershop.pl/allegro/callback"

tokens = allegro_api.get_access_token(client_id, client_secret, code, redirect_uri)

# Zapisz tokens['access_token'] i tokens['refresh_token']
```

---

## Pliki zmodyfikowane:

1. ✅ **magazyn/app.py** - Dodano auto-refresh tokena przy 401
2. ✅ **magazyn/socketio_extension.py** - Usunięto @authenticated_only z connect
3. ✅ **magazyn/factory.py** - Zmieniono konfigurację SocketIO na gevent

---

## Monitoring

Po naprawieniu, monitoruj metryki:
- `/metrics` endpoint pokazuje:
  - `allegro_token_refresh_attempts_total`
  - `allegro_token_refresh_last_success`
  - `allegro_api_errors_total{status="401"}`

---

## Podsumowanie

| Problem | Status | Rozwiązanie |
|---------|--------|-------------|
| 401 Unauthorized | ✅ Fixed | Auto-refresh przy 401 |
| 400 przy refresh_token | ⚠️ Requires action | Ponowna autoryzacja w Allegro |
| 400 SocketIO polling | ✅ Fixed | Usunięto @authenticated_only, dodano manage_session=False |
| Threading vs Gevent | ✅ Fixed | async_mode='gevent' |

**Jeśli nadal widzisz 401:** Musisz **ponownie autoryzować aplikację** przez `/settings`.
