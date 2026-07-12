"""Idempotentna wysylka powiadomien Messenger dla wiadomosci Allegro."""

from __future__ import annotations

import logging

from sqlalchemy import text

from .messenger import send_messenger

logger = logging.getLogger(__name__)


def notify_allegro_message_once(conn, message_id: str, message_text: str) -> bool:
    """Wyslij powiadomienie Messenger co najwyzej raz na wiadomosc Allegro.

    Jesli wysylka sie nie uda, flaga pozostaje False i worker sprobuje ponownie
    przy kolejnej synchronizacji.
    """
    row = conn.execute(
        text("SELECT messenger_notified FROM messages WHERE id = :mid"),
        {"mid": message_id},
    ).fetchone()
    if not row:
        logger.warning("Pomijam Messenger - brak wiadomosci %s w bazie", message_id)
        return False
    if row.messenger_notified:
        return False

    if not send_messenger(message_text):
        logger.warning("Messenger nieudany dla wiadomosci Allegro %s", message_id)
        return False

    conn.execute(
        text("UPDATE messages SET messenger_notified = TRUE WHERE id = :mid"),
        {"mid": message_id},
    )
    logger.info("Messenger wyslany dla wiadomosci Allegro %s", message_id)
    return True


__all__ = ["notify_allegro_message_once"]
