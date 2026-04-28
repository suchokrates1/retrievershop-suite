"""Upload i download zalacznikow dyskusji Allegro."""

from __future__ import annotations

import logging

from requests.exceptions import HTTPError

from .. import allegro_api
from ..config import settings

logger = logging.getLogger(__name__)

ALLOWED_ATTACHMENT_TYPES = {
    "image/png": ".png",
    "image/gif": ".gif",
    "image/bmp": ".bmp",
    "image/tiff": ".tiff",
    "image/jpeg": ".jpg",
    "application/pdf": ".pdf",
}
ISSUE_ATTACHMENT_LIMIT_BYTES = 2_097_152


def upload_discussion_attachment(file_storage, *, source: str = "messaging", log=None) -> tuple[dict, int]:
    """Przeslij zalacznik do Allegro i zwroc payload dla frontendu."""
    active_logger = log or logger
    token = getattr(settings, "ALLEGRO_ACCESS_TOKEN", None)
    if not token:
        return {"error": "Brak tokenu Allegro"}, 401

    if file_storage is None:
        return {"error": "Brak pliku"}, 400
    if file_storage.filename == "":
        return {"error": "Nie wybrano pliku"}, 400

    content_type = file_storage.content_type
    if content_type not in ALLOWED_ATTACHMENT_TYPES:
        return {
            "error": f"Nieobsługiwany typ pliku: {content_type}. Dozwolone: {', '.join(ALLOWED_ATTACHMENT_TYPES.keys())}"
        }, 400

    try:
        file_content = file_storage.read()
        filename = file_storage.filename
        if source == "issue":
            if len(file_content) > ISSUE_ATTACHMENT_LIMIT_BYTES:
                return {"error": "Plik za duży (max 2MB dla dyskusji/reklamacji)"}, 400
            attachment_id = allegro_api.upload_issue_attachment_complete(
                token,
                filename,
                file_content,
                content_type,
            )
        else:
            attachment_id = allegro_api.upload_attachment_complete(
                token,
                filename,
                file_content,
                content_type,
            )

        return {
            "id": attachment_id,
            "filename": filename,
            "size": len(file_content),
            "mimeType": content_type,
        }, 200
    except HTTPError as exc:
        status_code = getattr(getattr(exc, "response", None), "status_code", 0)
        active_logger.exception("Błąd API Allegro przy przesyłaniu załącznika")
        if status_code == 401:
            return {"error": "Token wygasł"}, 401
        return {"error": f"Błąd API: {status_code}"}, 502
    except Exception:
        active_logger.exception("Błąd przy przesyłaniu załącznika")
        return {"error": "Nie udało się przesłać załącznika"}, 500


def download_discussion_attachment(attachment_id: str, *, source: str = "messaging", log=None) -> tuple[bytes | dict, int]:
    """Pobierz zawartosc zalacznika z Allegro."""
    active_logger = log or logger
    token = getattr(settings, "ALLEGRO_ACCESS_TOKEN", None)
    if not token:
        return {"error": "Brak tokenu Allegro"}, 401

    try:
        if source == "issue":
            return allegro_api.download_issue_attachment(token, attachment_id), 200
        return allegro_api.download_attachment(token, attachment_id), 200
    except HTTPError as exc:
        status_code = getattr(getattr(exc, "response", None), "status_code", 0)
        active_logger.exception("Błąd API Allegro przy pobieraniu załącznika")
        if status_code == 401:
            return {"error": "Token wygasł"}, 401
        if status_code == 404:
            return {"error": "Załącznik nie znaleziony"}, 404
        return {"error": f"Błąd API: {status_code}"}, 502
    except Exception:
        active_logger.exception("Błąd przy pobieraniu załącznika")
        return {"error": "Nie udało się pobrać załącznika"}, 500


__all__ = [
    "ALLOWED_ATTACHMENT_TYPES",
    "download_discussion_attachment",
    "upload_discussion_attachment",
]
