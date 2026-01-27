"""
Modul do synchronizacji dyskusji i wiadomosci Allegro.

Wyodrebniony z print_agent.py dla lepszej organizacji kodu.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Callable

from ..db import sqlite_connect
from ..notifications import send_messenger
from ..utils import short_preview
from ..allegro_api import (
    fetch_discussions,
    fetch_discussion_chat,
    fetch_message_threads,
    fetch_thread_messages,
    send_discussion_message,
    send_thread_message,
)
from requests.exceptions import HTTPError


logger = logging.getLogger(__name__)


# Funkcja short_preview importowana z magazyn.utils


class AllegroSyncService:
    """
    Serwis do synchronizacji dyskusji i wiadomosci Allegro.
    
    Uzycie:
        service = AllegroSyncService(db_file, settings, save_state_callback)
        service.check_discussions(access_token)
        service.check_messages(access_token)
    """
    
    def __init__(
        self, 
        db_file: str,
        settings: Any,
        save_state_callback: Optional[Callable[[str, str], None]] = None
    ):
        """
        Args:
            db_file: Sciezka do pliku bazy SQLite
            settings: Obiekt ustawien z ALLEGRO_AUTORESPONDER_* 
            save_state_callback: Funkcja do zapisywania stanu (key, value)
        """
        self.db_file = db_file
        self.settings = settings
        self._save_state = save_state_callback or (lambda k, v: None)
    
    def _get_auto_reply_config(self) -> tuple[bool, str]:
        """Pobiera konfiguracje autorespondera."""
        auto_enabled = bool(getattr(self.settings, "ALLEGRO_AUTORESPONDER_ENABLED", False))
        auto_reply_text = getattr(
            self.settings,
            "ALLEGRO_AUTORESPONDER_MESSAGE",
            None,
        ) or "Dziękujemy za wiadomość. Postaramy się odpowiedzieć jak najszybciej."
        return auto_enabled, auto_reply_text
    
    def check_discussions(self, access_token: str) -> None:
        """
        Sprawdza nowe dyskusje Allegro i synchronizuje z baza.
        
        Args:
            access_token: Token dostepu Allegro
        """
        auto_enabled, auto_reply_text = self._get_auto_reply_config()
        
        try:
            discussions = fetch_discussions(access_token).get("issues", [])
        except Exception as exc:
            logger.error("Blad pobierania dyskusji Allegro: %s", exc)
            return
        
        if not discussions:
            return
        
        with sqlite_connect(self.db_file) as conn:
            cur = conn.cursor()
            for discussion in discussions:
                self._process_discussion(
                    cur, discussion, access_token, 
                    auto_enabled, auto_reply_text
                )
        
        self._save_state("last_discussion_check", datetime.now(timezone.utc).isoformat())
    
    def _process_discussion(
        self, 
        cur, 
        discussion: Dict[str, Any],
        access_token: str,
        auto_enabled: bool,
        auto_reply_text: str
    ) -> None:
        """Przetwarza pojedyncza dyskusje."""
        discussion_id = str(discussion.get("id")) if discussion.get("id") is not None else None
        if not discussion_id:
            return
        
        buyer = (discussion.get("buyer") or {}).get("login") or "Kupujący"
        subject = discussion.get("subject") or buyer
        
        # Upsert watku
        cur.execute("SELECT id FROM threads WHERE id = ?", (discussion_id,))
        exists = cur.fetchone()
        if not exists:
            cur.execute(
                "INSERT INTO threads (id, title, author, type, read) VALUES (?, ?, ?, ?, ?)",
                (discussion_id, subject, buyer, "dyskusja", 1),
            )
        else:
            cur.execute(
                "UPDATE threads SET title = ?, author = ? WHERE id = ?",
                (subject, buyer, discussion_id),
            )
        
        # Pobierz wiadomosci
        try:
            chat_payload = fetch_discussion_chat(access_token, discussion_id, limit=100)
        except Exception as exc:
            logger.error("Blad pobierania wiadomosci dyskusji %s: %s", discussion_id, exc)
            return
        
        chat_messages = chat_payload.get("chat", []) or []
        chat_messages.sort(key=lambda entry: entry.get("date") or "")
        
        latest_timestamp = None
        last_buyer_message = None
        
        for msg in chat_messages:
            msg_id_raw = msg.get("id")
            if msg_id_raw is None:
                continue
            msg_id = str(msg_id_raw)
            
            cur.execute("SELECT 1 FROM messages WHERE id = ?", (msg_id,))
            if cur.fetchone():
                latest_timestamp = msg.get("date") or latest_timestamp
                continue
            
            author_info = msg.get("author") or {}
            author_login = author_info.get("login") or buyer
            content = msg.get("text", "")
            created_at = msg.get("date") or datetime.now(timezone.utc).isoformat()
            
            cur.execute(
                "INSERT INTO messages (id, thread_id, author, content, created_at) VALUES (?, ?, ?, ?, ?)",
                (msg_id, discussion_id, author_login, content, created_at),
            )
            latest_timestamp = created_at
            
            if (author_info.get("role") or "").upper() == "BUYER":
                last_buyer_message = {
                    "login": author_login,
                    "text": content,
                    "created_at": created_at,
                }
                cur.execute("UPDATE threads SET read = 0 WHERE id = ?", (discussion_id,))
        
        if latest_timestamp:
            cur.execute(
                "UPDATE threads SET last_message_at = ? WHERE id = ?",
                (latest_timestamp, discussion_id),
            )
        
        # Powiadomienie i autoresponder
        if last_buyer_message:
            preview = short_preview(last_buyer_message["text"], normalize_whitespace=True)
            send_messenger(
                f"Użytkownik {last_buyer_message['login']} napisał w dyskusji: \"{preview}\""
            )
            
            if auto_enabled:
                self._send_auto_reply_discussion(
                    cur, access_token, discussion_id, auto_reply_text
                )
    
    def _send_auto_reply_discussion(
        self, 
        cur, 
        access_token: str, 
        discussion_id: str, 
        reply_text: str
    ) -> None:
        """Wysyla autoresponder do dyskusji jesli jeszcze nie wyslano."""
        cur.execute(
            "SELECT discussion_id FROM allegro_replied_discussions WHERE discussion_id = ?",
            (discussion_id,),
        )
        if cur.fetchone():
            return
        
        try:
            send_discussion_message(access_token, discussion_id, reply_text)
            cur.execute(
                "INSERT INTO allegro_replied_discussions (discussion_id, replied_at) VALUES (?, ?)",
                (discussion_id, datetime.now(timezone.utc).isoformat()),
            )
        except Exception as exc:
            logger.error("Blad wysylania autorespondera do dyskusji %s: %s", discussion_id, exc)
    
    def check_messages(self, access_token: str) -> None:
        """
        Sprawdza nowe wiadomosci Allegro i synchronizuje z baza.
        
        Args:
            access_token: Token dostepu Allegro
        """
        auto_enabled, auto_reply_text = self._get_auto_reply_config()
        
        try:
            threads = fetch_message_threads(access_token).get("threads", [])
        except Exception as exc:
            logger.error("Blad pobierania wiadomosci Allegro: %s", exc)
            return
        
        if not threads:
            return
        
        with sqlite_connect(self.db_file) as conn:
            cur = conn.cursor()
            for thread in threads:
                self._process_message_thread(
                    cur, thread, access_token,
                    auto_enabled, auto_reply_text
                )
        
        self._save_state("last_message_check", datetime.now(timezone.utc).isoformat())
    
    def _process_message_thread(
        self,
        cur,
        thread: Dict[str, Any],
        access_token: str,
        auto_enabled: bool,
        auto_reply_text: str
    ) -> None:
        """Przetwarza pojedynczy watek wiadomosci."""
        thread_id_raw = thread.get("id")
        if thread_id_raw is None:
            return
        thread_id = str(thread_id_raw)
        
        interlocutor = (thread.get("interlocutor") or {}).get("login") or "Kupujący"
        is_read_remote = bool(thread.get("read", True))
        
        # Upsert watku
        cur.execute("SELECT id FROM threads WHERE id = ?", (thread_id,))
        exists = cur.fetchone()
        if not exists:
            cur.execute(
                "INSERT INTO threads (id, title, author, type, read) VALUES (?, ?, ?, ?, ?)",
                (thread_id, interlocutor, interlocutor, "wiadomość", 1 if is_read_remote else 0),
            )
        else:
            cur.execute(
                "UPDATE threads SET title = ?, author = ? WHERE id = ?",
                (thread.get("topic") or interlocutor, interlocutor, thread_id),
            )
        
        # Pobierz wiadomosci
        try:
            messages_payload = fetch_thread_messages(access_token, thread_id, limit=100)
        except HTTPError as exc:
            status_code = getattr(getattr(exc, "response", None), "status_code", 0)
            if status_code == 422:
                logger.debug("Watek %s nie ma dostepnych wiadomosci (422), pomijam", thread_id)
                return
            logger.error("Blad pobierania tresci watku %s: %s", thread_id, exc)
            return
        except Exception as exc:
            logger.error("Blad pobierania tresci watku %s: %s", thread_id, exc)
            return
        
        messages = messages_payload.get("messages", []) or []
        messages.sort(key=lambda entry: entry.get("createdAt") or "")
        
        latest_timestamp = None
        last_interlocutor_message = None
        
        for msg in messages:
            msg_id_raw = msg.get("id")
            if msg_id_raw is None:
                continue
            msg_id = str(msg_id_raw)
            
            cur.execute("SELECT 1 FROM messages WHERE id = ?", (msg_id,))
            if cur.fetchone():
                latest_timestamp = msg.get("createdAt") or latest_timestamp
                continue
            
            author_info = msg.get("author") or {}
            author_login = author_info.get("login") or interlocutor
            content = msg.get("text", "")
            created_at = msg.get("createdAt") or datetime.now(timezone.utc).isoformat()
            
            cur.execute(
                "INSERT INTO messages (id, thread_id, author, content, created_at) VALUES (?, ?, ?, ?, ?)",
                (msg_id, thread_id, author_login, content, created_at),
            )
            latest_timestamp = created_at
            
            if author_info.get("isInterlocutor"):
                last_interlocutor_message = {
                    "login": author_login,
                    "text": content,
                    "created_at": created_at,
                }
                cur.execute("UPDATE threads SET read = 0 WHERE id = ?", (thread_id,))
        
        if latest_timestamp:
            cur.execute(
                "UPDATE threads SET last_message_at = ? WHERE id = ?",
                (latest_timestamp, thread_id),
            )
        
        # Powiadomienie i autoresponder
        if last_interlocutor_message:
            preview = short_preview(last_interlocutor_message["text"], normalize_whitespace=True)
            send_messenger(
                f"Użytkownik {last_interlocutor_message['login']} napisał wiadomość: \"{preview}\""
            )
            
            if auto_enabled:
                self._send_auto_reply_thread(
                    cur, access_token, thread_id, auto_reply_text
                )
    
    def _send_auto_reply_thread(
        self,
        cur,
        access_token: str,
        thread_id: str,
        reply_text: str
    ) -> None:
        """Wysyla autoresponder do watku jesli jeszcze nie wyslano."""
        cur.execute(
            "SELECT thread_id FROM allegro_replied_threads WHERE thread_id = ?",
            (thread_id,),
        )
        if cur.fetchone():
            return
        
        try:
            send_thread_message(access_token, thread_id, reply_text)
            cur.execute(
                "INSERT INTO allegro_replied_threads (thread_id, replied_at) VALUES (?, ?)",
                (thread_id, datetime.now(timezone.utc).isoformat()),
            )
        except Exception as exc:
            logger.error("Blad wysylania autorespondera do watku %s: %s", thread_id, exc)
