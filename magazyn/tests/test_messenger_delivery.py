"""Testy idempotentnej wysylki powiadomien Messenger."""

from sqlalchemy import text

from magazyn.notifications.messenger import MESSENGER_GRAPH_API_VERSION, MESSENGER_API_URL
from magazyn.notifications.messenger_delivery import notify_allegro_message_once


def test_messenger_api_uses_current_graph_version():
    assert MESSENGER_GRAPH_API_VERSION == "v25.0"
    assert MESSENGER_API_URL.endswith("/v25.0/me/messages")


def test_notify_allegro_message_once_sends_only_once(app, monkeypatch):
    sent = []

    monkeypatch.setattr(
        "magazyn.notifications.messenger_delivery.send_messenger",
        lambda text: sent.append(text) or True,
    )

    with app.app_context():
        from magazyn.db import db_connect

        with db_connect() as conn:
            conn.execute(
                text(
                    "INSERT INTO threads (id, title, author, type, read) "
                    "VALUES ('thread-1', 'Test', 'buyer', 'wiadomość', 0)"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO messages (id, thread_id, author, content, messenger_notified) "
                    "VALUES ('msg-1', 'thread-1', 'buyer', 'Czy macie rozmiar L?', 0)"
                )
            )

        with db_connect() as conn:
            first = notify_allegro_message_once(conn, "msg-1", "Nowa wiadomosc")
            second = notify_allegro_message_once(conn, "msg-1", "Nowa wiadomosc")

            row = conn.execute(
                text("SELECT messenger_notified FROM messages WHERE id = 'msg-1'")
            ).fetchone()

    assert first is True
    assert second is False
    assert len(sent) == 1
    assert bool(row.messenger_notified)


def test_notify_allegro_message_once_retries_after_failed_send(app, monkeypatch):
    attempts = {"count": 0}

    def flaky_send(_text):
        attempts["count"] += 1
        return attempts["count"] >= 2

    monkeypatch.setattr(
        "magazyn.notifications.messenger_delivery.send_messenger",
        flaky_send,
    )

    with app.app_context():
        from magazyn.db import db_connect

        with db_connect() as conn:
            conn.execute(
                text(
                    "INSERT INTO threads (id, title, author, type, read) "
                    "VALUES ('thread-2', 'Test', 'buyer', 'wiadomość', 0)"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO messages (id, thread_id, author, content, messenger_notified) "
                    "VALUES ('msg-2', 'thread-2', 'buyer', 'Pytanie o produkt', 0)"
                )
            )

        with db_connect() as conn:
            first = notify_allegro_message_once(conn, "msg-2", "Retry test")
            second = notify_allegro_message_once(conn, "msg-2", "Retry test")

            row = conn.execute(
                text("SELECT messenger_notified FROM messages WHERE id = 'msg-2'")
            ).fetchone()

    assert first is False
    assert second is True
    assert attempts["count"] == 2
    assert bool(row.messenger_notified)
