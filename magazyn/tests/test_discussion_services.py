import io

from werkzeug.datastructures import FileStorage

from magazyn.config import settings
from magazyn.services import discussion_attachments, discussion_messages
from magazyn.services.discussion_attachments import upload_discussion_attachment
from magazyn.services.discussion_messages import get_thread_messages_payload
from magazyn.services.discussion_threads import (
    build_discussions_context,
    create_local_thread,
    mark_thread_as_read,
)


def test_discussion_thread_service_creates_and_lists_local_thread(app):
    with app.app_context():
        payload, status_code = create_local_thread(
            {"title": "Test Thread", "type": "dyskusja", "message": "Test message"},
            "tester",
        )

        assert status_code == 201
        assert payload["thread"]["title"] == "Test Thread"

        context = build_discussions_context("tester")

        assert context["can_reply"] is False
        assert context["threads"][0]["id"] == payload["id"]
        assert context["threads"][0]["source"] == "local"


def test_discussion_thread_service_marks_thread_as_read(app):
    with app.app_context():
        payload, _ = create_local_thread(
            {"title": "Unread", "type": "dyskusja", "message": "Hej"},
            "tester",
        )

        response, status_code = mark_thread_as_read(payload["id"])

        assert status_code == 200
        assert response["success"] is True
        assert response["thread"]["read"] is True


def test_discussion_messages_service_fetches_messaging_payload(app, monkeypatch):
    with app.app_context():
        settings.ALLEGRO_ACCESS_TOKEN = "token-test"

        monkeypatch.setattr(
            discussion_messages.allegro_api,
            "fetch_thread_messages",
            lambda token, thread_id: {
                "messages": [
                    {
                        "id": "msg-1",
                        "author": {"login": "client", "role": "BUYER"},
                        "text": "Ala &amp; kot",
                        "createdAt": "2026-04-28T10:00:00Z",
                        "attachments": [
                            {"id": "att-1", "fileName": "plik.pdf", "mimeType": "application/pdf"}
                        ],
                    }
                ]
            },
        )

        payload, status_code = get_thread_messages_payload("thread-1")

        assert status_code == 200
        assert payload["thread"] == {"id": "thread-1", "source": "messaging"}
        assert payload["messages"][0]["content"] == "Ala & kot"
        assert payload["messages"][0]["attachments"][0]["filename"] == "plik.pdf"


def test_discussion_attachment_service_uploads_allowed_file(app, monkeypatch):
    with app.app_context():
        settings.ALLEGRO_ACCESS_TOKEN = "token-test"

        monkeypatch.setattr(
            discussion_attachments.allegro_api,
            "upload_attachment_complete",
            lambda token, filename, file_content, content_type: "att-123",
        )
        file_storage = FileStorage(
            stream=io.BytesIO(b"pdf"),
            filename="plik.pdf",
            content_type="application/pdf",
        )

        payload, status_code = upload_discussion_attachment(file_storage)

        assert status_code == 200
        assert payload == {
            "id": "att-123",
            "filename": "plik.pdf",
            "size": 3,
            "mimeType": "application/pdf",
        }
