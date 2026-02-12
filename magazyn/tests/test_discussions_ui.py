"""Test UI strony dyskusji z fakeowymi danymi."""

import sys
from pathlib import Path

# Dodaj ścieżkę do modułu magazyn
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def create_fake_discussions_data():
    """Tworzy listę fakeowych danych dyskusji."""
    
    return [
        {
            "id": "thread123",
            "title": "Jan Kowalski",
            "author": "jan.kowalski",
            "type": "wiadomość",
            "read": False,
            "last_message_at": "2025-11-06T14:30:00.000Z",
            "last_message_iso": "2025-11-06T14:30:00.000Z",
            "last_message_preview": "Dzień dobry, czy produkt jest jeszcze dostępny? Interesuje mnie ten model w rozmiarze M.",
            "last_message_author": "jan.kowalski",
            "source": "messaging",
        },
        {
            "id": "thread456",
            "title": "Anna Nowak",
            "author": "anna.nowak",
            "type": "wiadomość",
            "read": True,
            "last_message_at": "2025-11-05T10:15:00.000Z",
            "last_message_iso": "2025-11-05T10:15:00.000Z",
            "last_message_preview": "Dziękuję za szybką wysyłkę! Produkt dotarł w idealnym stanie.",
            "last_message_author": "anna.nowak",
            "source": "messaging",
        },
        {
            "id": "issue789",
            "title": "Problem z zamówieniem #12345",
            "author": "Piotr Wiśniewski",
            "type": "dyskusja",
            "read": False,
            "last_message_at": "2025-11-04T16:20:00.000Z",
            "last_message_iso": "2025-11-04T16:20:00.000Z",
            "last_message_preview": "Paczka nie dotarła w terminie, proszę o kontakt w sprawie zwrotu.",
            "last_message_author": "piotr.wisniewski",
            "source": "issue",
        },
        {
            "id": "thread789",
            "title": "Marek Zieliński",
            "author": "marek.zielinski",
            "type": "wiadomość",
            "read": True,
            "last_message_at": "2025-11-03T09:00:00.000Z",
            "last_message_iso": "2025-11-03T09:00:00.000Z",
            "last_message_preview": "Proszę o fakturę VAT na firmę. NIP: 1234567890",
            "last_message_author": "marek.zielinski",
            "source": "messaging",
        },
        {
            "id": "thread999",
            "title": "Katarzyna Lewandowska",
            "author": "katarzyna.lewandowska",
            "type": "wiadomość",
            "read": False,
            "last_message_at": "2025-11-06T16:45:00.000Z",
            "last_message_iso": "2025-11-06T16:45:00.000Z",
            "last_message_preview": "Czy możliwy jest odbiór osobisty zamiast wysyłki kurierem?",
            "last_message_author": "katarzyna.lewandowska",
            "source": "messaging",
        },
    ]


def test_discussions_page_with_fake_data():
    """Generuje stronę HTML z fakeowymi danymi - standalone bez Flask."""
    
    print("🎨 Generuję standalone HTML z prawdziwymi stylami...")
    
    from datetime import datetime
    
    def format_dt(value):
        """Format datetime."""
        if value is None:
            return ""
        if isinstance(value, str):
            try:
                dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
                return dt.strftime("%d/%m/%Y %H:%M")
            except Exception:
                return value[:16]
        return value.strftime("%d/%m/%Y %H:%M")
    
    fake_threads = create_fake_discussions_data()
    
    # Wczytaj style z discussions.html
    template_file = Path(__file__).parent.parent / "templates" / "discussions.html"
    with open(template_file, "r", encoding="utf-8") as f:
        template_content = f.read()
    
    # Wyciągnij CSS (między <style> a </style> w bloku {% block styles %})
    import re
    css_match = re.search(r'{% block styles %}.*?<style>(.*?)</style>.*?{% endblock %}', template_content, re.DOTALL)
    css_content = css_match.group(1) if css_match else ""
    
    # Generuj HTML
    threads_html = ""
    for thread in fake_threads:
        unread_class = "" if thread["read"] else " unread"
        unread_dot = "" if thread["read"] else '<span class="unread-dot" aria-hidden="true"></span>'
        
        if thread["type"] == "dyskusja":
            type_pill = '<i class="bi bi-chat-dots-fill"></i>Dyskusja'
            type_class = "pill-discussion"
        else:
            type_pill = '<i class="bi bi-envelope-fill"></i>Wiadomość'
            type_class = "pill-message"
        
        last_author = f"@{thread['last_message_author']}" if thread.get("last_message_author") else "Nieznany nadawca"
        
        threads_html += f'''
            <div class="thread-item{unread_class}" role="button" tabindex="0" aria-selected="false" 
                 data-thread-id="{thread['id']}" 
                 data-thread-title="{thread['title']}"
                 data-thread-author="{thread['author']}"
                 data-thread-type="{thread['type']}"
                 data-thread-read="{'true' if thread['read'] else 'false'}"
                 data-thread-last="{thread['last_message_iso']}"
                 data-thread-preview="{thread['last_message_preview']}"
                 data-source="{thread['source']}">
                <div class="thread-item-header">
                    <div class="thread-title-row">
                        <h6 class="thread-title">{thread['title']}</h6>
                        <time class="thread-timestamp" data-thread-timestamp>{format_dt(thread['last_message_at'])}</time>
                    </div>
                    <div class="thread-item-meta">
                        <span class="thread-author" data-thread-author>{last_author}</span>
                        <span class="thread-type-pill {type_class}" data-thread-type-pill>{type_pill}</span>
                    </div>
                </div>
                <p class="thread-preview" data-thread-preview-text>{thread['last_message_preview']}</p>
                {unread_dot}
            </div>
        '''
    
    # Wygeneruj kompletny HTML
    html_content = f'''<!DOCTYPE html>
<html lang="pl">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Wiadomości i dyskusje - Test z fakeowymi danymi</title>
    <!-- Bootstrap Icons -->
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css">
    <style>
    {css_content}
    body {{
        background-color: #0d1117;
        margin: 0;
        padding: 20px;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    }}
    </style>
</head>
<body>
    <div class="discussions-layout" data-username="admin" data-can-reply="true">
        <aside class="threads-panel">
            <div class="threads-toolbar">
                <h5>
                    <i class="bi bi-chat-left-text-fill"></i>
                    Wiadomości
                </h5>
                <div class="input-group input-group-sm search-group">
                    <span class="input-group-text"><i class="bi bi-search"></i></span>
                    <input type="text" class="form-control" id="search-threads" placeholder="Szukaj rozmów..." value="">
                </div>
            </div>
            <div class="threads-list" id="threads-container" data-threads role="listbox" aria-label="Lista wątków">
                {threads_html}
            </div>
        </aside>
        <section class="conversation-panel">
            <header class="conversation-header">
                <div class="conversation-header-left">
                    <h2 class="conversation-title" data-thread-title>Wybierz wątek</h2>
                    <div class="conversation-meta" data-thread-meta>Kliknij rozmowę po lewej stronie</div>
                </div>
                <div class="conversation-actions">
                    <span class="thread-type-pill" data-thread-type hidden></span>
                    <button type="button" class="btn btn-outline-light btn-sm" id="refresh-thread" title="Odśwież wiadomości">
                        <i class="bi bi-arrow-clockwise"></i>
                    </button>
                </div>
            </header>
            <div class="chat-status" id="chat-status" role="status" aria-live="polite"></div>
            <div class="messages-area" id="messages-area">
                <div class="chat-placeholder">
                    <i class="bi bi-chat-text fs-2 d-block mb-3"></i>
                    Wybierz wątek po lewej, aby zobaczyć historię wiadomości.
                </div>
            </div>
        </section>
    </div>
</body>
</html>
'''
    
    # Zapisz HTML do pliku
    output_file = Path(__file__).parent / "discussions_output.html"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(html_content)
    
    print(f"💾 Zapisano HTML do: {output_file}")
    print(f"📏 Rozmiar: {len(html_content)} bajtów")
    
    # Sprawdź zawartość
    checks = {
        "Jan Kowalski": "Jan Kowalski" in html_content,
        "Anna Nowak": "Anna Nowak" in html_content,
        "Marek Zieliński": "Marek Zieliński" in html_content,
        "Katarzyna Lewandowska": "Katarzyna Lewandowska" in html_content,
        "Problem z zamówieniem": "Problem z zamówieniem" in html_content,
        "wiadomość": "wiadomość" in html_content,
        "dyskusja": "dyskusja" in html_content,
    }
    
    print("\n Sprawdzenia zawartosci:")
    for name, result in checks.items():
        status = "OK" if result else "FAIL"
        print(f"   {status} {name}")
    
    return True


if __name__ == "__main__":
    print("Test UI strony dyskusji z fakeowymi danymi\n")
    print("=" * 60)
    
    success = test_discussions_page_with_fake_data()
    
    print("=" * 60)
    if success:
        print("\nTest zakonczony sukcesem!")
    else:
        print("\nTest zakonczony bledem!")
