# Plan Naprawy i Rozwoju Modułu Discussions

**Data:** 6 listopada 2025  
**Status:** Do implementacji

---

## 🚨 CZĘŚĆ 1: NAPRAWA BŁĘDÓW CSP (Content Security Policy)

### Problem
Przeglądarka blokuje zasoby z zewnętrznych CDN z powodu restrykcyjnej polityki CSP:

```
❌ https://static.cloudflareinsights.com/beacon.min.js (CloudFlare)
❌ https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js
❌ https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css
❌ favicon.ico (404)
```

### Analiza Kodu
**Plik:** `magazyn/factory.py` (linie 84-95)

```python
csp = (
    "default-src 'self'; "
    "img-src 'self' https://retrievershop.pl data:; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "  # ✓ OK
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "   # ✓ OK
    "font-src 'self' https://cdn.jsdelivr.net data:; "
    "connect-src 'self'; "  # ⚠️ Blokuje CloudFlare
    "object-src 'none'; "
    "base-uri 'self'; "
    "frame-ancestors 'self'"
)
```

### Rozwiązanie

**Priorytet:** 🔴 KRYTYCZNY (30 min)

#### 1.1. Aktualizacja CSP w `factory.py`

```python
csp = (
    "default-src 'self'; "
    "img-src 'self' https://retrievershop.pl data: blob:; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://static.cloudflareinsights.com; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "font-src 'self' https://cdn.jsdelivr.net data:; "
    "connect-src 'self' https://cloudflareinsights.com; "  # Dodane CloudFlare
    "object-src 'none'; "
    "base-uri 'self'; "
    "frame-ancestors 'self'"
)
```

#### 1.2. Dodanie favicon.ico

Utwórz plik `magazyn/static/favicon.ico` lub dodaj do `base.html`:

```html
<link rel="icon" href="data:," />  <!-- Pusty favicon, żeby zatrzymać błąd 404 -->
```

#### 1.3. Aktualizacja testów CSP

**Plik:** `magazyn/tests/test_security_headers.py`

Zaktualizuj asercję, aby uwzględniała CloudFlare:

```python
"connect-src 'self' https://cloudflareinsights.com; "
```

---

## 🎯 CZĘŚĆ 2: IMPLEMENTACJA WYSOKIEGO PRIORYTETU

### 2.1. Real-time Updates (WebSocket) ⭐⭐⭐⭐⭐

**Czas:** 2-3 dni  
**Priorytet:** WYSOKI  
**Technologia:** Flask-SocketIO + Socket.IO client

#### Architektura

```
┌──────────────┐         WebSocket          ┌──────────────┐
│   Frontend   │ ←─────────────────────────→ │   Backend    │
│ discussions  │                             │ Flask-SocketIO│
└──────────────┘                             └──────────────┘
       ↓                                              ↓
   Socket.IO                              ┌───────────────────┐
   Event Listeners                        │  Allegro Scraper  │
   - message_received                     │  (co 30s)         │
   - thread_updated                       └───────────────────┘
   - user_typing                                    ↓
                                          emit('message_received')
```

#### Pliki do utworzenia/modyfikacji

**A. `magazyn/socketio_extension.py` (NOWY)**

```python
"""WebSocket extension for real-time discussions."""
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask import request, session
from functools import wraps

socketio = SocketIO(cors_allowed_origins="*")

def authenticated_only(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if 'username' not in session:
            return False
        return f(*args, **kwargs)
    return wrapped

@socketio.on('connect')
@authenticated_only
def handle_connect():
    username = session.get('username')
    print(f'[SocketIO] User {username} connected')
    emit('connected', {'username': username})

@socketio.on('disconnect')
def handle_disconnect():
    username = session.get('username', 'anonymous')
    print(f'[SocketIO] User {username} disconnected')

@socketio.on('join_thread')
@authenticated_only
def handle_join_thread(data):
    thread_id = data.get('thread_id')
    if thread_id:
        join_room(thread_id)
        username = session.get('username')
        print(f'[SocketIO] {username} joined thread {thread_id}')

@socketio.on('leave_thread')
@authenticated_only
def handle_leave_thread(data):
    thread_id = data.get('thread_id')
    if thread_id:
        leave_room(thread_id)
        username = session.get('username')
        print(f'[SocketIO] {username} left thread {thread_id}')

@socketio.on('typing')
@authenticated_only
def handle_typing(data):
    thread_id = data.get('thread_id')
    is_typing = data.get('is_typing', False)
    if thread_id:
        username = session.get('username')
        emit('user_typing', {
            'username': username,
            'is_typing': is_typing
        }, room=thread_id, skip_sid=request.sid)

def broadcast_new_message(thread_id, message_payload):
    """Emit new message to all users in thread room."""
    socketio.emit('message_received', {
        'thread_id': thread_id,
        'message': message_payload
    }, room=thread_id)

def broadcast_thread_update(thread_id, thread_payload):
    """Emit thread metadata update."""
    socketio.emit('thread_updated', {
        'thread_id': thread_id,
        'thread': thread_payload
    }, to=thread_id)
```

**B. Aktualizacja `magazyn/factory.py`**

```python
from .socketio_extension import socketio

def create_app(test_config=None):
    # ... existing code ...
    
    # Initialize SocketIO
    socketio.init_app(app)
    
    return app
```

**C. Aktualizacja `magazyn/wsgi.py`**

```python
from magazyn.factory import create_app
from magazyn.socketio_extension import socketio

app = create_app()

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5000, debug=True)
```

**D. Aktualizacja `magazyn/app.py` - endpoint `/discussions/<thread_id>/send`**

```python
from .socketio_extension import broadcast_new_message

@bp.route("/discussions/<string:thread_id>/send", methods=["POST"])
@login_required
def send_message(thread_id):
    # ... existing code ...
    
    # Po pomyślnym wysłaniu i zapisaniu do DB:
    payload = {
        "id": new_message.id,
        "author": new_message.author,
        "content": new_message.content,
        "created_at": _serialize_dt(new_message.created_at),
        "thread": _thread_payload(thread, last_message=new_message),
    }
    
    # Broadcast do innych użytkowników
    broadcast_new_message(thread_id, payload)
    
    return payload
```

**E. Frontend - aktualizacja `discussions.html`**

```html
<!-- Dodaj przed zamykającym </body> w base.html -->
<script src="https://cdn.socket.io/4.5.4/socket.io.min.js" 
        integrity="sha384-/KNQL8Nu5gCHLqwqfQjA689Hhoqgi2S84SNUxC3roTe4EhJ9AfLkp8QiQcU8AMzI" 
        crossorigin="anonymous"></script>

<!-- W discussions.html na końcu bloku {% block scripts %} -->
<script>
document.addEventListener('DOMContentLoaded', function() {
    const socket = io();
    let currentRoom = null;
    let typingTimeout = null;

    socket.on('connect', () => {
        console.log('[WebSocket] Connected');
    });

    socket.on('message_received', (data) => {
        console.log('[WebSocket] New message:', data);
        if (data.thread_id === currentThreadId) {
            // Dodaj wiadomość do UI bez przeładowania
            appendMessage(data.message);
            // Aktualizuj thread card
            if (data.message.thread) {
                updateThreadCard(data.message.thread);
            }
        } else {
            // Aktualizuj badge "nieprzeczytane" na thread card
            const threadItem = document.querySelector(`[data-thread-id="${data.thread_id}"]`);
            if (threadItem && data.message.thread) {
                updateThreadCard(data.message.thread);
            }
        }
    });

    socket.on('thread_updated', (data) => {
        console.log('[WebSocket] Thread updated:', data);
        updateThreadCard(data.thread);
    });

    socket.on('user_typing', (data) => {
        console.log('[WebSocket] User typing:', data);
        showTypingIndicator(data.username, data.is_typing);
    });

    // Gdy użytkownik klika wątek
    function joinThreadRoom(threadId) {
        if (currentRoom) {
            socket.emit('leave_thread', { thread_id: currentRoom });
        }
        socket.emit('join_thread', { thread_id: threadId });
        currentRoom = threadId;
    }

    // Typing indicator
    messageInput.addEventListener('input', () => {
        if (!currentThreadId) return;
        
        socket.emit('typing', { thread_id: currentThreadId, is_typing: true });
        
        clearTimeout(typingTimeout);
        typingTimeout = setTimeout(() => {
            socket.emit('typing', { thread_id: currentThreadId, is_typing: false });
        }, 2000);
    });

    function showTypingIndicator(username, isTyping) {
        const typingDiv = document.getElementById('typing-indicator');
        if (!typingDiv) return;
        
        if (isTyping) {
            typingDiv.textContent = `${username} pisze...`;
            typingDiv.classList.remove('d-none');
        } else {
            typingDiv.classList.add('d-none');
        }
    }

    // Podłącz do loadThread
    const originalLoadThread = window.loadThread;
    window.loadThread = function(threadEl, options) {
        const result = originalLoadThread(threadEl, options);
        const threadId = threadEl.dataset.threadId;
        if (threadId) {
            joinThreadRoom(threadId);
        }
        return result;
    };
});
</script>
```

**F. Dodaj typing indicator do HTML**

```html
<div class="messages-area" id="messagesArea">
    <!-- existing messages -->
</div>
<div id="typing-indicator" class="typing-indicator d-none"></div>
<form id="messageForm" class="composer">
    <!-- existing form -->
</form>
```

**G. CSS dla typing indicator**

```css
.typing-indicator {
    padding: 0.5rem 1rem;
    color: #8b949e;
    font-size: 0.875rem;
    font-style: italic;
    animation: fadeIn 0.3s;
}
```

**H. Aktualizacja `requirements.txt`**

```
flask-socketio==5.3.4
python-socketio==5.9.0
```

**I. Integracja z Allegro Scraper**

W `magazyn/allegro_scraper.py` lub tam gdzie odbierasz nowe wiadomości z Allegro:

```python
from .socketio_extension import broadcast_new_message

def process_new_allegro_message(thread_id, message_data):
    # ... save to DB ...
    
    # Broadcast do wszystkich klientów
    broadcast_new_message(thread_id, message_payload)
```

---

### 2.2. Grupowanie Wiadomości po Datach ⭐⭐⭐⭐

**Czas:** 2 godziny  
**Priorytet:** WYSOKI

#### Implementacja

**A. Aktualizacja JavaScript w `discussions.html`**

```javascript
function renderMessages(messages, threadInfo) {
    messagesArea.innerHTML = '';
    if (!messages.length) {
        messagesArea.innerHTML = `
            <div class="chat-placeholder">
                <i class="bi bi-inboxes fs-2 d-block mb-3"></i>
                Nie znaleziono wiadomości w tym wątku.
            </div>
        `;
        return;
    }

    const fragment = document.createDocumentFragment();
    let lastDate = null;

    messages.forEach((message) => {
        const messageDate = new Date(message.created_at).toLocaleDateString('pl-PL', {
            year: 'numeric',
            month: 'long',
            day: 'numeric'
        });

        // Dodaj separator daty jeśli zmienił się dzień
        if (messageDate !== lastDate) {
            const dateSeparator = document.createElement('div');
            dateSeparator.className = 'date-separator';
            dateSeparator.innerHTML = `<span>${messageDate}</span>`;
            fragment.appendChild(dateSeparator);
            lastDate = messageDate;
        }

        fragment.appendChild(renderMessage(message));
    });

    messagesArea.appendChild(fragment);
    messagesArea.scrollTop = messagesArea.scrollHeight;

    if (threadInfo) {
        updateHeaderFromPayload(threadInfo);
    }
}
```

**B. CSS dla separatorów**

```css
.date-separator {
    display: flex;
    align-items: center;
    text-align: center;
    margin: 1.5rem 0;
    color: #8b949e;
    font-size: 0.8rem;
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}

.date-separator::before,
.date-separator::after {
    content: '';
    flex: 1;
    border-bottom: 1px solid #30363d;
}

.date-separator span {
    padding: 0 1rem;
    background: #0d1117;
}

/* Dzisiaj - zielony */
.date-separator.today span {
    color: #3fb950;
}

/* Wczoraj - niebieski */
.date-separator.yesterday span {
    color: #58a6ff;
}
```

**C. Rozszerzona logika dla "Dzisiaj" / "Wczoraj"**

```javascript
function getDateLabel(dateStr) {
    const messageDate = new Date(dateStr);
    const today = new Date();
    const yesterday = new Date(today);
    yesterday.setDate(yesterday.getDate() - 1);

    const isToday = messageDate.toDateString() === today.toDateString();
    const isYesterday = messageDate.toDateString() === yesterday.toDateString();

    if (isToday) return { label: 'Dzisiaj', class: 'today' };
    if (isYesterday) return { label: 'Wczoraj', class: 'yesterday' };

    return {
        label: messageDate.toLocaleDateString('pl-PL', {
            year: 'numeric',
            month: 'long',
            day: 'numeric'
        }),
        class: ''
    };
}

// W renderMessages:
const { label, class: dateClass } = getDateLabel(message.created_at);
if (label !== lastDateLabel) {
    const dateSeparator = document.createElement('div');
    dateSeparator.className = `date-separator ${dateClass}`;
    dateSeparator.innerHTML = `<span>${label}</span>`;
    fragment.appendChild(dateSeparator);
    lastDateLabel = label;
}
```

---

### 2.3. Desktop Notifications ⭐⭐⭐⭐

**Czas:** 2 godziny  
**Priorytet:** WYSOKI

#### Implementacja

**A. JavaScript w `discussions.html`**

```javascript
// Request notification permission
let notificationsEnabled = false;

async function requestNotificationPermission() {
    if (!('Notification' in window)) {
        console.warn('Przeglądarka nie wspiera powiadomień');
        return false;
    }

    if (Notification.permission === 'granted') {
        notificationsEnabled = true;
        return true;
    }

    if (Notification.permission !== 'denied') {
        const permission = await Notification.requestPermission();
        notificationsEnabled = permission === 'granted';
        return notificationsEnabled;
    }

    return false;
}

function showDesktopNotification(title, options = {}) {
    if (!notificationsEnabled) return;

    // Nie pokazuj powiadomienia jeśli zakładka jest aktywna
    if (!document.hidden) return;

    const notification = new Notification(title, {
        icon: '/static/favicon.ico',
        badge: '/static/favicon.ico',
        tag: 'discussion-message',
        ...options
    });

    notification.onclick = function() {
        window.focus();
        notification.close();
    };

    // Auto-close po 5 sekundach
    setTimeout(() => notification.close(), 5000);
}

// Integracja z WebSocket
socket.on('message_received', (data) => {
    // ... existing code ...

    // Jeśli wiadomość z innego wątku niż aktualnie otwarty
    if (data.thread_id !== currentThreadId) {
        const author = data.message.author || 'Nieznany';
        const preview = data.message.content.substring(0, 100);
        
        showDesktopNotification(`Nowa wiadomość od ${author}`, {
            body: preview,
            data: { thread_id: data.thread_id }
        });

        // Opcjonalnie: odtwórz dźwięk
        playNotificationSound();
    }
});

// Na starcie aplikacji
document.addEventListener('DOMContentLoaded', async () => {
    // ... existing code ...

    // Zapytaj o uprawnienia do powiadomień
    await requestNotificationPermission();

    // Pokaż przycisk ustawień powiadomień
    const notifBtn = document.getElementById('notificationSettings');
    if (notifBtn) {
        notifBtn.addEventListener('click', async () => {
            const enabled = await requestNotificationPermission();
            showStatus(
                enabled 
                    ? 'Powiadomienia włączone!' 
                    : 'Powiadomienia wyłączone lub zablokowane przez przeglądarkę.',
                enabled ? 'success' : 'warning'
            );
        });
    }
});

function playNotificationSound() {
    // Opcjonalny dźwięk powiadomienia
    const audio = new Audio('/static/notification.mp3');
    audio.volume = 0.3;
    audio.play().catch(() => {
        // Ignore autoplay policy errors
    });
}
```

**B. HTML - przycisk w toolbarze**

```html
<div class="conversation-header-right">
    <button id="notificationSettings" class="btn btn-sm btn-outline-secondary" 
            title="Ustawienia powiadomień">
        <i class="bi bi-bell"></i>
    </button>
    <button id="refreshButton" class="btn btn-sm btn-outline-secondary" 
            title="Odśwież wątek">
        <i class="bi bi-arrow-clockwise"></i>
    </button>
</div>
```

---

### 2.4. Paginacja Wiadomości ⭐⭐⭐⭐

**Czas:** 4 godziny  
**Priorytet:** ŚREDNI

#### Backend - `magazyn/app.py`

```python
@bp.route("/discussions/<thread_id>")
@login_required
def get_messages(thread_id):
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    
    with get_session() as db:
        thread = (
            db.query(Thread)
            .options(joinedload(Thread.messages))
            .filter_by(id=thread_id)
            .first()
        )
        if not thread:
            return {"error": "Thread not found"}, 404

        # Sortuj i paginuj
        total_messages = len(thread.messages)
        ordered_messages = sorted(
            thread.messages,
            key=lambda message: message.created_at or datetime.min,
        )
        
        # Oblicz offset
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        paginated_messages = ordered_messages[start_idx:end_idx]
        
        has_more = end_idx < total_messages
        
        thread_payload = _thread_payload(
            thread,
            last_message=ordered_messages[-1] if ordered_messages else None,
        )
        
        return {
            "thread": thread_payload,
            "messages": [
                {
                    "id": message.id,
                    "author": message.author,
                    "content": message.content,
                    "created_at": _serialize_dt(message.created_at),
                }
                for message in paginated_messages
            ],
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total": total_messages,
                "has_more": has_more
            }
        }
```

#### Frontend - Infinite Scroll

```javascript
let currentPage = 1;
let isLoadingMore = false;
let hasMoreMessages = true;

async function loadThread(threadEl, { forceReload = false } = {}) {
    // ... existing code ...
    
    currentPage = 1;
    hasMoreMessages = true;
    
    try {
        const response = await fetch(
            `/discussions/${threadId}?page=${currentPage}&per_page=50`,
            { credentials: 'same-origin' }
        );
        // ... existing code ...
        
        const payload = await response.json();
        hasMoreMessages = payload.pagination?.has_more || false;
        
        renderMessages(payload.messages || [], payload.thread);
        
        // Dodaj scroll listener
        messagesArea.addEventListener('scroll', handleScroll);
        
    } catch (error) {
        // ... existing error handling ...
    }
}

async function loadMoreMessages() {
    if (isLoadingMore || !hasMoreMessages || !currentThreadId) return;
    
    isLoadingMore = true;
    currentPage++;
    
    showLoadingIndicator();
    
    try {
        const response = await fetch(
            `/discussions/${currentThreadId}?page=${currentPage}&per_page=50`,
            { credentials: 'same-origin' }
        );
        
        if (!response.ok) throw new Error('Failed to load more messages');
        
        const payload = await response.json();
        hasMoreMessages = payload.pagination?.has_more || false;
        
        // Zapisz pozycję scroll przed dodaniem
        const scrollBefore = messagesArea.scrollHeight - messagesArea.scrollTop;
        
        // Dodaj starsze wiadomości na górze
        prependMessages(payload.messages || []);
        
        // Przywróć pozycję scroll
        messagesArea.scrollTop = messagesArea.scrollHeight - scrollBefore;
        
    } catch (error) {
        console.error('Error loading more messages:', error);
        currentPage--;
    } finally {
        isLoadingMore = false;
        hideLoadingIndicator();
    }
}

function handleScroll() {
    // Jeśli scrollujemy do góry i jesteśmy blisko szczytu
    if (messagesArea.scrollTop < 100) {
        loadMoreMessages();
    }
}

function prependMessages(messages) {
    const fragment = document.createDocumentFragment();
    messages.forEach(message => {
        fragment.appendChild(renderMessage(message));
    });
    messagesArea.prepend(fragment);
}

function showLoadingIndicator() {
    const loader = document.createElement('div');
    loader.id = 'loadingMore';
    loader.className = 'text-center py-2';
    loader.innerHTML = '<div class="spinner-border spinner-border-sm" role="status"></div>';
    messagesArea.prepend(loader);
}

function hideLoadingIndicator() {
    const loader = document.getElementById('loadingMore');
    if (loader) loader.remove();
}
```

---

## 🔧 CZĘŚĆ 3: REFAKTOR I OPTYMALIZACJE

### 3.1. Optymalizacja Zapytań DB

**Problem:** N+1 queries przy ładowaniu wątków z wiadomościami

**Rozwiązanie:**

```python
# W discussions()
threads_from_db = (
    db.query(Thread)
    .options(
        joinedload(Thread.messages)  # ✅ Already done
    )
    .order_by(Thread.last_message_at.desc(), Thread.title.asc())
    .limit(100)  # Dodaj limit dla performance
    .all()
)
```

### 3.2. Cache dla Thread Payload

```python
from functools import lru_cache
from hashlib import md5

def _thread_cache_key(thread):
    # Klucz cache based on thread state
    return f"{thread.id}:{thread.last_message_at}:{thread.read}"

@lru_cache(maxsize=100)
def _thread_payload_cached(cache_key, thread_dict, last_message_dict):
    # Cached version - przyjmuje dict zamiast ORM objects
    return {
        "id": thread_dict["id"],
        "title": thread_dict["title"],
        "author": thread_dict["author"],
        "type": thread_dict["type"],
        "read": thread_dict["read"],
        "last_message_at": thread_dict["last_message_at"],
        "last_message_preview": _message_preview(last_message_dict["content"]) if last_message_dict else None,
        "last_message_author": last_message_dict["author"] if last_message_dict else None,
    }
```

### 3.3. Separacja Logiki - Service Layer

**Nowy plik:** `magazyn/domain/discussions.py`

```python
"""Business logic for discussions module."""
from typing import Optional, List, Dict, Any
from datetime import datetime
from ..models import Thread, Message
from ..db import get_session

class DiscussionService:
    """Service layer for discussions operations."""
    
    def __init__(self):
        self.preview_length = 160
    
    def get_all_threads(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Fetch all threads with pagination."""
        with get_session() as db:
            threads = (
                db.query(Thread)
                .options(joinedload(Thread.messages))
                .order_by(Thread.last_message_at.desc())
                .limit(limit)
                .all()
            )
            return [self._serialize_thread(t) for t in threads]
    
    def get_thread_messages(
        self, 
        thread_id: str, 
        page: int = 1, 
        per_page: int = 50
    ) -> Dict[str, Any]:
        """Get paginated messages for thread."""
        with get_session() as db:
            thread = (
                db.query(Thread)
                .options(joinedload(Thread.messages))
                .filter_by(id=thread_id)
                .first()
            )
            
            if not thread:
                raise ValueError(f"Thread {thread_id} not found")
            
            messages = sorted(
                thread.messages,
                key=lambda m: m.created_at or datetime.min
            )
            
            total = len(messages)
            start = (page - 1) * per_page
            end = start + per_page
            
            return {
                "thread": self._serialize_thread(thread),
                "messages": [self._serialize_message(m) for m in messages[start:end]],
                "pagination": {
                    "page": page,
                    "per_page": per_page,
                    "total": total,
                    "has_more": end < total
                }
            }
    
    def mark_thread_read(self, thread_id: str) -> bool:
        """Mark thread as read."""
        with get_session() as db:
            thread = db.query(Thread).filter_by(id=thread_id).first()
            if thread:
                thread.read = True
                db.flush()
                return True
            return False
    
    def _serialize_thread(self, thread: Thread) -> Dict[str, Any]:
        """Convert thread ORM to dict."""
        last_msg = self._get_latest_message(thread)
        return {
            "id": thread.id,
            "title": thread.title,
            "author": thread.author,
            "type": thread.type,
            "read": thread.read,
            "last_message_at": thread.last_message_at.isoformat() if thread.last_message_at else None,
            "last_message_preview": self._message_preview(last_msg.content) if last_msg else None,
            "last_message_author": last_msg.author if last_msg else None,
        }
    
    def _serialize_message(self, message: Message) -> Dict[str, Any]:
        """Convert message ORM to dict."""
        return {
            "id": message.id,
            "author": message.author,
            "content": message.content,
            "created_at": message.created_at.isoformat() if message.created_at else None,
        }
    
    def _get_latest_message(self, thread: Thread) -> Optional[Message]:
        """Get most recent message from thread."""
        if not thread.messages:
            return None
        return max(thread.messages, key=lambda m: m.created_at or datetime.min)
    
    def _message_preview(self, text: str) -> str:
        """Generate preview of message content."""
        if not text:
            return ""
        text = text.strip()
        if len(text) <= self.preview_length:
            return text
        return text[:self.preview_length].rsplit(' ', 1)[0] + '...'


# Singleton instance
discussion_service = DiscussionService()
```

**Aktualizacja `magazyn/app.py`:**

```python
from .domain.discussions import discussion_service

@bp.route("/discussions")
@login_required
def discussions():
    threads = discussion_service.get_all_threads(limit=100)
    can_reply = bool(getattr(settings, "ALLEGRO_ACCESS_TOKEN", None))
    autoresponder_enabled = bool(
        getattr(settings, "ALLEGRO_AUTORESPONDER_ENABLED", False)
    )
    return render_template(
        "discussions.html",
        threads=threads,
        username=session.get("username"),
        can_reply=can_reply,
        autoresponder_enabled=autoresponder_enabled,
    )

@bp.route("/discussions/<thread_id>")
@login_required
def get_messages(thread_id):
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    
    try:
        result = discussion_service.get_thread_messages(thread_id, page, per_page)
        return result
    except ValueError as e:
        return {"error": str(e)}, 404
```

### 3.4. Error Handling & Logging

**Nowy plik:** `magazyn/utils/error_handler.py`

```python
"""Centralized error handling utilities."""
from flask import jsonify, current_app
from functools import wraps
from requests.exceptions import HTTPError, RequestException

class APIError(Exception):
    """Custom API error."""
    def __init__(self, message, status_code=400, payload=None):
        super().__init__()
        self.message = message
        self.status_code = status_code
        self.payload = payload

def handle_api_errors(f):
    """Decorator for standardized error handling."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except APIError as e:
            current_app.logger.error(f"API Error: {e.message}")
            return jsonify({"error": e.message}), e.status_code
        except ValueError as e:
            current_app.logger.error(f"Validation Error: {str(e)}")
            return jsonify({"error": str(e)}), 400
        except HTTPError as e:
            status = getattr(getattr(e, "response", None), "status_code", 0)
            current_app.logger.exception(f"HTTP Error {status}: {str(e)}")
            if status == 401:
                msg = "Token Allegro wygasł. Odśwież integrację."
            else:
                msg = "Błąd komunikacji z Allegro."
            return jsonify({"error": msg}), 502
        except RequestException as e:
            current_app.logger.exception(f"Request Error: {str(e)}")
            return jsonify({"error": "Błąd połączenia z zewnętrznym API."}), 502
        except Exception as e:
            current_app.logger.exception(f"Unexpected error: {str(e)}")
            return jsonify({"error": "Wystąpił nieoczekiwany błąd."}), 500
    
    return decorated_function
```

**Użycie:**

```python
from .utils.error_handler import handle_api_errors, APIError

@bp.route("/discussions/<string:thread_id>/send", methods=["POST"])
@login_required
@handle_api_errors
def send_message(thread_id):
    payload = request.get_json(silent=True) or {}
    content = (payload.get("content") or "").strip()
    
    if not content:
        raise APIError("Treść wiadomości nie może być pusta.", 400)
    
    token = getattr(settings, "ALLEGRO_ACCESS_TOKEN", None)
    if not token:
        raise APIError("Brak tokenu Allegro.", 400)
    
    # ... rest of logic ...
```

### 3.5. Frontend Refaktor - Module Pattern

**Nowy plik:** `magazyn/static/discussions.js`

```javascript
/**
 * Discussions Module - Handles real-time messaging interface
 */
const DiscussionsApp = (function() {
    'use strict';

    // Private state
    let currentThreadId = null;
    let activeThreadEl = null;
    let isSending = false;
    let currentPage = 1;
    let hasMoreMessages = true;
    let socket = null;
    
    // Private DOM references
    let elements = {};
    
    // Configuration
    const config = {
        csrfToken: document.querySelector('meta[name="csrf-token"]')?.content,
        username: document.body.dataset.username?.toLowerCase(),
        perPage: 50,
        typingDebounce: 2000,
    };

    /**
     * Initialize DOM element references
     */
    function cacheDOMElements() {
        elements = {
            threadsContainer: document.getElementById('threadsContainer'),
            messagesArea: document.getElementById('messagesArea'),
            messageForm: document.getElementById('messageForm'),
            messageInput: document.getElementById('messageInput'),
            sendButton: document.getElementById('sendButton'),
            sendSpinner: document.getElementById('sendSpinner'),
            searchInput: document.getElementById('searchInput'),
            refreshButton: document.getElementById('refreshButton'),
            clearButton: document.getElementById('clearButton'),
            conversationHeader: document.querySelector('.conversation-header'),
            statusAlert: document.getElementById('statusAlert'),
        };
    }

    /**
     * Initialize WebSocket connection
     */
    function initializeWebSocket() {
        if (typeof io === 'undefined') {
            console.warn('Socket.IO not loaded, real-time features disabled');
            return;
        }

        socket = io();
        
        socket.on('connect', () => {
            console.log('[WS] Connected');
        });

        socket.on('message_received', handleIncomingMessage);
        socket.on('thread_updated', handleThreadUpdate);
        socket.on('user_typing', handleUserTyping);
    }

    /**
     * Handle incoming message via WebSocket
     */
    function handleIncomingMessage(data) {
        if (data.thread_id === currentThreadId) {
            MessageRenderer.appendMessage(data.message);
            ThreadManager.updateThreadCard(data.message.thread);
        } else {
            ThreadManager.updateThreadCard(data.message.thread);
            NotificationManager.show(
                `Nowa wiadomość od ${data.message.author}`,
                data.message.content
            );
        }
    }

    /**
     * Thread Management Module
     */
    const ThreadManager = {
        loadThread: async function(threadEl, { forceReload = false } = {}) {
            if (!threadEl) return;
            
            const threadId = threadEl.dataset.threadId;
            if (!threadId || (!forceReload && currentThreadId === threadId)) {
                return;
            }

            currentThreadId = threadId;
            activeThreadEl = threadEl;
            currentPage = 1;
            hasMoreMessages = true;

            this.setActiveThread(threadEl);
            UI.showLoading();

            try {
                const response = await API.fetchThreadMessages(threadId, currentPage);
                MessageRenderer.render(response.messages, response.thread);
                
                if (socket) {
                    socket.emit('join_thread', { thread_id: threadId });
                }
                
                await API.markThreadAsRead(threadId);
                
            } catch (error) {
                console.error('Error loading thread:', error);
                UI.showError(error.message);
            }
        },

        setActiveThread: function(threadEl) {
            document.querySelectorAll('.thread-item').forEach(item => {
                item.classList.remove('active');
                item.setAttribute('aria-selected', 'false');
            });
            threadEl.classList.add('active');
            threadEl.setAttribute('aria-selected', 'true');
        },

        updateThreadCard: function(threadData) {
            const threadEl = document.querySelector(`[data-thread-id="${threadData.id}"]`);
            if (!threadEl) return { shouldReorder: false };

            const wasUnread = threadEl.classList.contains('unread');
            
            if (threadData.read) {
                threadEl.classList.remove('unread');
            } else {
                threadEl.classList.add('unread');
            }

            const titleEl = threadEl.querySelector('.thread-title');
            const timestampEl = threadEl.querySelector('.thread-timestamp');
            const previewEl = threadEl.querySelector('.thread-preview');

            if (titleEl) titleEl.textContent = threadData.title;
            if (timestampEl) timestampEl.textContent = Utils.formatTimestamp(threadData.last_message_at);
            if (previewEl) previewEl.textContent = threadData.last_message_preview || '';

            const shouldReorder = !wasUnread && !threadData.read;
            return { shouldReorder };
        }
    };

    /**
     * Message Rendering Module
     */
    const MessageRenderer = {
        render: function(messages, threadInfo) {
            elements.messagesArea.innerHTML = '';
            
            if (!messages.length) {
                this.showEmptyState();
                return;
            }

            const fragment = document.createDocumentFragment();
            let lastDate = null;

            messages.forEach(message => {
                const dateLabel = Utils.getDateLabel(message.created_at);
                
                if (dateLabel !== lastDate) {
                    fragment.appendChild(this.createDateSeparator(dateLabel));
                    lastDate = dateLabel;
                }

                fragment.appendChild(this.createMessageElement(message));
            });

            elements.messagesArea.appendChild(fragment);
            this.scrollToBottom();

            if (threadInfo) {
                this.updateHeader(threadInfo);
            }
        },

        createMessageElement: function(message) {
            const wrapper = document.createElement('article');
            const isOwn = message.author.toLowerCase() === config.username;
            wrapper.className = `message-row ${isOwn ? 'message-outgoing' : 'message-incoming'}`;
            
            const timestamp = Utils.formatTimestamp(message.created_at, true);
            wrapper.innerHTML = `
                <div class="message-bubble ${isOwn ? 'outgoing' : 'incoming'}">
                    <div class="message-author">${isOwn ? 'Ty' : Utils.escapeHTML(message.author)}</div>
                    <div class="message-content">${Utils.escapeHTML(message.content).replace(/\n/g, '<br>')}</div>
                    <div class="message-meta">${timestamp}</div>
                </div>
            `;
            return wrapper;
        },

        createDateSeparator: function(label) {
            const separator = document.createElement('div');
            separator.className = 'date-separator';
            separator.innerHTML = `<span>${label}</span>`;
            return separator;
        },

        appendMessage: function(message) {
            const messageEl = this.createMessageElement(message);
            elements.messagesArea.appendChild(messageEl);
            this.scrollToBottom();
        },

        scrollToBottom: function() {
            elements.messagesArea.scrollTop = elements.messagesArea.scrollHeight;
        },

        showEmptyState: function() {
            elements.messagesArea.innerHTML = `
                <div class="chat-placeholder">
                    <i class="bi bi-inboxes fs-2 d-block mb-3"></i>
                    Nie znaleziono wiadomości w tym wątku.
                </div>
            `;
        },

        updateHeader: function(threadInfo) {
            const headerTitle = elements.conversationHeader.querySelector('.thread-title');
            const headerMeta = elements.conversationHeader.querySelector('.thread-meta');
            
            if (headerTitle) headerTitle.textContent = threadInfo.title || 'Wiadomość';
            if (headerMeta) {
                const metaAuthor = threadInfo.last_message_author || threadInfo.author;
                headerMeta.textContent = Utils.formatMeta(metaAuthor, threadInfo.last_message_at);
            }
        }
    };

    /**
     * API Communication Module
     */
    const API = {
        fetchThreadMessages: async function(threadId, page = 1) {
            const response = await fetch(
                `/discussions/${threadId}?page=${page}&per_page=${config.perPage}`,
                { credentials: 'same-origin' }
            );
            
            if (!response.ok) {
                throw new Error('Nie udało się pobrać wiadomości.');
            }
            
            return await response.json();
        },

        sendMessage: async function(threadId, content) {
            const response = await fetch(`/discussions/${threadId}/send`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': config.csrfToken,
                },
                credentials: 'same-origin',
                body: JSON.stringify({ content }),
            });

            const payload = await response.json();
            
            if (!response.ok) {
                throw new Error(payload.error || 'Wiadomość nie została wysłana.');
            }

            return payload;
        },

        markThreadAsRead: async function(threadId) {
            try {
                const response = await fetch(`/discussions/${threadId}/read`, {
                    method: 'POST',
                    headers: { 'X-CSRFToken': config.csrfToken },
                    credentials: 'same-origin',
                });
                
                if (response.ok) {
                    const payload = await response.json();
                    if (payload.thread) {
                        ThreadManager.updateThreadCard(payload.thread);
                    }
                }
            } catch (error) {
                console.error('Failed to mark as read:', error);
            }
        }
    };

    /**
     * UI State Management
     */
    const UI = {
        showLoading: function() {
            if (elements.messagesArea) {
                elements.messagesArea.innerHTML = `
                    <div class="chat-placeholder">
                        <div class="spinner-border text-primary" role="status">
                            <span class="visually-hidden">Ładowanie...</span>
                        </div>
                    </div>
                `;
            }
        },

        showError: function(message) {
            if (elements.statusAlert) {
                elements.statusAlert.className = 'alert alert-danger';
                elements.statusAlert.textContent = message;
                elements.statusAlert.hidden = false;
                
                setTimeout(() => {
                    elements.statusAlert.hidden = true;
                }, 5000);
            }
        },

        setSendingState: function(isSending) {
            if (elements.sendButton) {
                elements.sendButton.disabled = isSending;
            }
            if (elements.sendSpinner) {
                elements.sendSpinner.classList.toggle('d-none', !isSending);
            }
        }
    };

    /**
     * Utility Functions
     */
    const Utils = {
        escapeHTML: function(str) {
            const div = document.createElement('div');
            div.textContent = str;
            return div.innerHTML;
        },

        formatTimestamp: function(isoString, includeTime = false) {
            if (!isoString) return '';
            const date = new Date(isoString);
            const options = {
                day: 'numeric',
                month: 'short',
                year: 'numeric',
            };
            if (includeTime) {
                options.hour = '2-digit';
                options.minute = '2-digit';
            }
            return date.toLocaleString('pl-PL', options);
        },

        getDateLabel: function(isoString) {
            const date = new Date(isoString);
            const today = new Date();
            const yesterday = new Date(today);
            yesterday.setDate(yesterday.getDate() - 1);

            if (date.toDateString() === today.toDateString()) {
                return 'Dzisiaj';
            }
            if (date.toDateString() === yesterday.toDateString()) {
                return 'Wczoraj';
            }

            return date.toLocaleDateString('pl-PL', {
                year: 'numeric',
                month: 'long',
                day: 'numeric'
            });
        },

        formatMeta: function(author, timestamp) {
            return `${author} • ${this.formatTimestamp(timestamp)}`;
        }
    };

    /**
     * Desktop Notifications Module
     */
    const NotificationManager = {
        enabled: false,

        init: async function() {
            if (!('Notification' in window)) return;

            if (Notification.permission === 'granted') {
                this.enabled = true;
            } else if (Notification.permission !== 'denied') {
                const permission = await Notification.requestPermission();
                this.enabled = permission === 'granted';
            }
        },

        show: function(title, body) {
            if (!this.enabled || !document.hidden) return;

            const notification = new Notification(title, {
                body: body.substring(0, 100),
                icon: '/static/favicon.ico',
                tag: 'discussion-message',
            });

            notification.onclick = function() {
                window.focus();
                notification.close();
            };

            setTimeout(() => notification.close(), 5000);
        }
    };

    /**
     * Event Handlers
     */
    function bindEvents() {
        // Thread click
        if (elements.threadsContainer) {
            elements.threadsContainer.addEventListener('click', (e) => {
                const item = e.target.closest('.thread-item');
                if (item) {
                    ThreadManager.loadThread(item, { forceReload: true });
                }
            });
        }

        // Message form submit
        if (elements.messageForm) {
            elements.messageForm.addEventListener('submit', async (e) => {
                e.preventDefault();
                
                if (!currentThreadId || !elements.messageInput.value.trim() || isSending) {
                    return;
                }

                const content = elements.messageInput.value.trim();
                UI.setSendingState(true);

                try {
                    const payload = await API.sendMessage(currentThreadId, content);
                    MessageRenderer.appendMessage(payload);
                    
                    if (payload.thread) {
                        ThreadManager.updateThreadCard(payload.thread);
                    }

                    elements.messageInput.value = '';
                    elements.messageInput.focus();
                    
                } catch (error) {
                    console.error('Send error:', error);
                    UI.showError(error.message);
                } finally {
                    UI.setSendingState(false);
                }
            });
        }

        // Enter to send
        if (elements.messageInput) {
            elements.messageInput.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    elements.messageForm.requestSubmit();
                }
            });
        }

        // Search threads
        if (elements.searchInput) {
            elements.searchInput.addEventListener('input', () => {
                const query = elements.searchInput.value.toLowerCase();
                const threads = elements.threadsContainer.querySelectorAll('.thread-item');
                
                threads.forEach(thread => {
                    const text = thread.innerText.toLowerCase();
                    thread.style.display = text.includes(query) ? '' : 'none';
                });
            });
        }

        // Refresh button
        if (elements.refreshButton) {
            elements.refreshButton.addEventListener('click', () => {
                if (activeThreadEl) {
                    ThreadManager.loadThread(activeThreadEl, { forceReload: true });
                }
            });
        }
    }

    /**
     * Public API
     */
    return {
        init: function() {
            cacheDOMElements();
            bindEvents();
            initializeWebSocket();
            NotificationManager.init();

            // Load first unread thread
            const firstThread = elements.threadsContainer?.querySelector('.thread-item.unread') ||
                              elements.threadsContainer?.querySelector('.thread-item');
            
            if (firstThread) {
                ThreadManager.loadThread(firstThread);
            }
        }
    };
})();

// Initialize on DOM ready
document.addEventListener('DOMContentLoaded', function() {
    DiscussionsApp.init();
});
```

**Aktualizacja `discussions.html` - użyj zewnętrznego pliku JS:**

```html
{% block scripts %}
<script src="{{ url_for('static', filename='discussions.js') }}"></script>
{% endblock %}
```

---

## 📋 CZĘŚĆ 4: PODSUMOWANIE PRIORYTETÓW

### Pilne (Dzisiaj)
1. ✅ **Naprawa CSP** - 30 min
2. ✅ **Dodanie favicon** - 5 min
3. ✅ **Aktualizacja testów** - 10 min

### Wysokiy Priorytet (Tydzień 1)
4. 🔄 **WebSocket Real-time** - 2-3 dni
5. 🔄 **Grupowanie dat** - 2 godz
6. 🔄 **Desktop Notifications** - 2 godz

### Średni Priorytet (Tydzień 2)
7. 🔄 **Paginacja wiadomości** - 4 godz
8. 🔄 **Service Layer refactor** - 4 godz
9. 🔄 **Error handling** - 2 godz

### Niski Priorytet (Tydzień 3-4)
10. 🔄 **Frontend modularyzacja** - 1 dzień
11. 🔄 **Cache optimization** - 4 godz
12. 🔄 **Analytics & metrics** - 1 dzień

---

## 🧪 CZĘŚĆ 5: TESTY DO DODANIA

### Test WebSocket

```python
# magazyn/tests/test_socketio.py
import pytest
from magazyn.socketio_extension import socketio

def test_websocket_connect(client):
    """Test WebSocket connection."""
    socketio_client = socketio.test_client(client.application)
    assert socketio_client.is_connected()

def test_join_thread_room(client, auth_session):
    """Test joining thread room."""
    socketio_client = socketio.test_client(client.application)
    socketio_client.emit('join_thread', {'thread_id': 'test-123'})
    # Assert user is in room
```

### Test Paginacji

```python
# magazyn/tests/test_discussions_pagination.py
def test_get_messages_pagination(client, auth_session, sample_thread_with_messages):
    """Test message pagination."""
    response = client.get('/discussions/test-thread-1?page=1&per_page=10')
    assert response.status_code == 200
    data = response.get_json()
    assert 'pagination' in data
    assert data['pagination']['page'] == 1
    assert data['pagination']['per_page'] == 10
```

---

## 📖 CZĘŚĆ 6: DOKUMENTACJA

### Aktualizacja README.md

Dodaj sekcję:

```markdown
## Moduł Discussions - Real-time Messaging

### Funkcje:
- ✅ Real-time updates via WebSocket
- ✅ Desktop notifications
- ✅ Message pagination
- ✅ Date grouping
- ✅ Typing indicators
- ✅ Thread management

### Technologie:
- **Frontend**: Vanilla JS (Module Pattern)
- **Backend**: Flask + Flask-SocketIO
- **Real-time**: Socket.IO
- **Database**: SQLAlchemy ORM

### Konfiguracja:

```bash
pip install -r requirements.txt
python -m flask run
```

### WebSocket URL:
Domyślnie używa tego samego porta co Flask (5000).
Dla produkcji skonfiguruj nginx jako reverse proxy.
```

---

## ✅ KOŃCOWE CHECKLIST

```
□ 1. Naprawa CSP w factory.py
□ 2. Dodanie favicon.ico
□ 3. Aktualizacja test_security_headers.py
□ 4. Instalacja flask-socketio
□ 5. Utworzenie socketio_extension.py
□ 6. Aktualizacja factory.py (socketio init)
□ 7. Aktualizacja wsgi.py (socketio.run)
□ 8. Dodanie WebSocket do discussions.html
□ 9. Implementacja date separators
□ 10. Dodanie desktop notifications
□ 11. Implementacja paginacji (backend)
□ 12. Implementacja infinite scroll (frontend)
□ 13. Utworzenie discussions service layer
□ 14. Refaktor app.py (użycie service)
□ 15. Utworzenie error_handler.py
□ 16. Modularyzacja discussions.js
□ 17. Aktualizacja discussions.html (użycie zewnętrznego JS)
□ 18. Dodanie testów WebSocket
□ 19. Dodanie testów paginacji
□ 20. Aktualizacja dokumentacji
```

---

**KONIEC PLANU**
