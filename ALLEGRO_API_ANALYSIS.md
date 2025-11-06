# 📋 Analiza zgodności z Allegro API - Moduł Discussions

## ✅ Zaimplementowane funkcje API

### 1. Centrum Wiadomości (`/messaging/*`)
| Endpoint API | Funkcja w kodzie | Status |
|-------------|------------------|--------|
| `GET /messaging/threads` | `fetch_message_threads()` | ✅ Zaimplementowane |
| `GET /messaging/threads/{threadId}/messages` | `fetch_thread_messages()` | ✅ Zaimplementowane |
| `POST /messaging/threads/{threadId}/messages` | `send_thread_message()` | ✅ Zaimplementowane |

### 2. Dyskusje i Reklamacje (`/sale/issues/*`)
| Endpoint API | Funkcja w kodzie | Status |
|-------------|------------------|--------|
| `GET /sale/issues` | `fetch_discussion_issues()` | ✅ **DODANE** (było brakujące) |
| `GET /sale/issues/{issueId}/chat` | `fetch_discussion_chat()` | ✅ Zaimplementowane |
| `POST /sale/issues/{issueId}/message` | `send_discussion_message()` | ✅ Zaimplementowane |

## ❌ Problem: Backend NIE wykorzystuje API Allegro

### Obecna implementacja (NIEPRAWIDŁOWA):
```python
@bp.route("/discussions")
def discussions():
    with get_session() as db:
        threads_from_db = db.query(Thread).all()  # ❌ Lokalna baza!
        # ...
```

### Co jest nie tak:
1. **Dane są w lokalnej bazie SQLite** zamiast pobierane z API Allegro
2. **Wątki nie są synchronizowane** z prawdziwymi wiadomościami Allegro
3. **Brak integracji** z Centrum Wiadomości Allegro
4. **Niemożliwa komunikacja** z kupu jącymi przez Allegro

## 🔧 Wymagane zmiany

### 1. Endpoint `/discussions` - lista wątków

**PRZED (lokalna baza):**
```python
@bp.route("/discussions")
def discussions():
    with get_session() as db:
        threads_from_db = db.query(Thread).all()
        # Zwraca dane z lokalnej bazy
```

**PO (API Allegro):**
```python
@bp.route("/discussions")
def discussions():
    token = getattr(settings, "ALLEGRO_ACCESS_TOKEN", None)
    if not token:
        return render_template("discussions.html", threads=[], error="No token")
    
    try:
        # Pobierz wątki z Allegro Centrum Wiadomości
        messaging_data = allegro_api.fetch_message_threads(token)
        messaging_threads = messaging_data.get("threads", [])
        
        # Pobierz dyskusje i reklamacje
        issues_data = allegro_api.fetch_discussion_issues(token)
        issues = issues_data.get("issues", [])
        
        # Połącz obie listy
        all_threads = _merge_threads_and_issues(messaging_threads, issues)
        
        return render_template("discussions.html", threads=all_threads)
    except HTTPError as e:
        # Obsługa błędów API
        return render_template("discussions.html", threads=[], error=str(e))
```

### 2. Endpoint `/discussions/<thread_id>` - wiadomości

**PRZED:**
```python
@bp.route("/discussions/<thread_id>")
def get_messages(thread_id):
    with get_session() as db:
        thread = db.query(Thread).filter_by(id=thread_id).first()
        # Zwraca wiadomości z lokalnej bazy
```

**PO:**
```python
@bp.route("/discussions/<thread_id>")
def get_messages(thread_id):
    token = getattr(settings, "ALLEGRO_ACCESS_TOKEN", None)
    if not token:
        return {"error": "No token"}, 401
    
    # Określ czy to wątek czy dyskusja (po ID lub parametrze)
    thread_type = request.args.get("type", "messaging")
    
    if thread_type == "issue":
        # Dyskusja/reklamacja
        data = allegro_api.fetch_discussion_chat(token, thread_id)
        messages = data.get("chat", [])
    else:
        # Centrum wiadomości
        data = allegro_api.fetch_thread_messages(token, thread_id)
        messages = data.get("messages", [])
    
    return {"messages": _format_messages(messages)}
```

### 3. Endpoint `/discussions/<thread_id>/send` - wysyłanie

**Obecnie:** Używa `send_thread_message()` - to jest OK!
**Wymaga:** Dodać rozróżnienie między wątkami a dyskusjami

```python
@bp.route("/discussions/<thread_id>/send", methods=["POST"])
def send_message(thread_id):
    payload = request.get_json()
    content = payload.get("content")
    thread_type = payload.get("type", "messaging")  # +DODANE
    
    token = getattr(settings, "ALLEGRO_ACCESS_TOKEN", None)
    
    if thread_type == "issue":
        response = allegro_api.send_discussion_message(token, thread_id, content)
    else:
        response = allegro_api.send_thread_message(token, thread_id, content)
    
    # Zapisz w lokalnej bazie jako cache (opcjonalnie)
    # ...
```

## 🎯 Struktura danych API vs Lokalna baza

### Centrum Wiadomości - GET /messaging/threads
```json
{
  "threads": [
    {
      "id": "dpYCg9auts9xpSojwC6DWPvyVKHraqDCZCiT70j6pcf",
      "interlocutor": {
        "id": "12345",
        "login": "buyer-login"
      },
      "read": false,
      "lastMessage": {
        "text": "Dziękuję za szybką odpowiedź",
        "author": { "role": "BUYER" },
        "createdAt": "2025-11-06T10:30:00.000Z"
      }
    }
  ]
}
```

### Dyskusje - GET /sale/issues
```json
{
  "issues": [
    {
      "id": "97ce67c8-823e-45d5-a280-c3e74aea1e2a",
      "type": "DISPUTE",  // lub "CLAIM"
      "subject": "NO_REFUND_AFTER_RETURNING_PRODUCT",
      "buyer": {
        "id": "93975873",
        "login": "test-buyer"
      },
      "chat": {
        "lastMessage": {
          "status": "NEW",
          "createdAt": "2025-06-22T18:47:54.632Z"
        },
        "messagesCount": 1
      }
    }
  ]
}
```

### Lokalna baza (Thread model) - DO USUNIĘCIA
```python
class Thread(Base):
    __tablename__ = "threads"
    id = Column(String, primary_key=True)
    title = Column(String, nullable=False)
    author = Column(String, nullable=False)
    type = Column(String, nullable=False)
    read = Column(Boolean, default=False)
    # ❌ Ta tabela nie powinna być używana dla danych Allegro!
```

## 📝 Rekomendacje

### Krótkoterminowe (Pilne):
1. ✅ **Dodano** `fetch_discussion_issues()` w `allegro_api.py`
2. ⚠️ **Zmienić** endpoint `/discussions` aby używał API zamiast lokalnej bazy
3. ⚠️ **Dodać** rozróżnienie między typami wątków (messaging vs issues)
4. ⚠️ **Dodać** obsługę błędów API (401, 403, 500)

### Długoterminowe:
1. **Usunąć** tabele `threads` i `messages` z lokalnej bazy (albo używać tylko jako cache)
2. **Dodać** synchronizację w tle (np. co 5 minut pobieraj nowe wątki)
3. **Dodać** webhook handler dla powiadomień real-time z Allegro
4. **Rozszerzyć** o załączniki (`/messaging/message-attachments`)
5. **Dodać** oznaczanie jako przeczytane (`PUT /messaging/threads/{threadId}/read`)

### Cache strategy (opcjonalnie):
- **Poziom 1**: Zawsze pobieraj z API (wolne, ale aktualne)
- **Poziom 2**: Cache w Redis/Memcached (szybkie, wymaga infrastruktury)
- **Poziom 3**: Cache w SQLite z TTL (kompromis)

```python
def get_threads_with_cache(token, ttl=300):  # 5 min cache
    cache_key = f"allegro_threads:{token[:8]}"
    cached = cache.get(cache_key)
    if cached and not is_expired(cached, ttl):
        return cached["data"]
    
    data = allegro_api.fetch_message_threads(token)
    cache.set(cache_key, {"data": data, "timestamp": time.time()})
    return data
```

## 🐛 Bug: Stylowanie nie wyświetla się

### Przyczyna: Cache przeglądarki
- Zmiany CSS w `discussions.html` są obecne w kodzie
- Przeglądarka używa starej wersji z cache

### Rozwiązanie:
1. **Hard refresh**: `Ctrl + Shift + R` (Chrome/Firefox)
2. **DevTools**: F12 → prawy przycisk na Refresh → "Empty Cache and Hard Reload"
3. **Incognito mode**: Otwórz w trybie prywatnym
4. **Version busting**: Dodaj `?v=2` do URLi CSS

Zobacz szczegóły w: `CACHE_CLEAR_INSTRUCTIONS.md`

## 🔗 Dokumentacja Allegro

- Centrum Wiadomości: https://developer.allegro.pl/tutorials/jak-zarzadzac-centrum-wiadomosci-XxWm2K890Fk
- Dyskusje i reklamacje: https://developer.allegro.pl/tutorials/jak-zarzadzac-dyskusjami-E7Zj6gK7ysE
- API Reference: https://developer.allegro.pl/documentation

## ✨ Podsumowanie

**Co działa:**
- ✅ Funkcje API w `allegro_api.py` są poprawnie zaimplementowane
- ✅ Stylowanie CSS jest nowoczesne i responsywne
- ✅ WebSocket real-time działa

**Co wymaga naprawy:**
- ❌ Backend używa lokalnej bazy zamiast API Allegro
- ❌ Brak synchronizacji z prawdziwymi wiadomościami Allegro
- ⚠️ Cache przeglądarki blokuje nowe style (wymagany hard refresh)

**Priorytet zmian:**
1. 🔴 **HIGH**: Przepisać endpoints na API Allegro
2. 🟡 **MEDIUM**: Dodać cache strategy
3. 🟢 **LOW**: Rozszerzyć o załączniki i webhooks
