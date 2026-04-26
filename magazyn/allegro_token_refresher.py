"""Background task refreshing Allegro OAuth tokens before expiry."""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from requests.exceptions import HTTPError, RequestException

from . import allegro_api
from .env_tokens import update_allegro_tokens
from .metrics import (
    ALLEGRO_TOKEN_REFRESH_ATTEMPTS_TOTAL,
    ALLEGRO_TOKEN_REFRESH_LAST_SUCCESS,
    ALLEGRO_TOKEN_REFRESH_RETRIES_TOTAL,
)
from .settings_store import SettingsPersistenceError, settings_store
from .utils import parse_optional_int

LOGGER = logging.getLogger(__name__)

TOKEN_FAILURE_NOTIFY_THRESHOLD = 3


def _parse_datetime(value: object) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class AllegroTokenRefresher:
    """Refresh Allegro OAuth tokens shortly before they expire."""

    def __init__(
        self,
        margin_seconds: int = 300,
        idle_interval_seconds: float = 60.0,
        error_backoff_initial: float = 30.0,
        error_backoff_max: float = 600.0,
    ) -> None:
        self._margin_seconds = margin_seconds
        self._idle_interval = idle_interval_seconds
        self._error_backoff_initial = error_backoff_initial
        self._error_backoff_max = error_backoff_max
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._consecutive_failures: int = 0
        self._notification_sent: bool = False

    def start(self) -> bool:
        """Start the background refresher thread."""

        with self._lock:
            if self._thread and self._thread.is_alive():
                return False
            self._stop_event.clear()
            thread = threading.Thread(
                target=self._run,
                name="AllegroTokenRefresher",
                daemon=True,
            )
            thread.start()
            self._thread = thread
            LOGGER.info(
                "Started Allegro token refresher with margin=%ss and idle interval=%ss",
                self._margin_seconds,
                self._idle_interval,
            )
            return True

    def stop(self) -> None:
        """Stop the background refresher thread."""

        with self._lock:
            if not self._thread:
                return
            self._stop_event.set()
            thread = self._thread
        thread.join()
        with self._lock:
            self._thread = None
            self._stop_event.clear()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _seconds_until_refresh(self) -> Optional[float]:
        access_token = settings_store.get("ALLEGRO_ACCESS_TOKEN")
        refresh_token = settings_store.get("ALLEGRO_REFRESH_TOKEN")
        if not access_token or not refresh_token:
            return None

        metadata_raw = settings_store.get("ALLEGRO_TOKEN_METADATA")
        metadata: dict[str, object] = {}
        if metadata_raw:
            try:
                loaded = json.loads(metadata_raw)
                if isinstance(loaded, dict):
                    metadata.update(loaded)
            except (TypeError, ValueError):
                LOGGER.debug("Failed to decode Allegro token metadata", exc_info=True)

        expires_at = _parse_datetime(metadata.get("expires_at"))
        if expires_at is None:
            expires_in = metadata.get("expires_in")
            if expires_in is None:
                expires_in = settings_store.get("ALLEGRO_TOKEN_EXPIRES_IN")
            expires_in_value = parse_optional_int(expires_in)
            obtained_at = _parse_datetime(metadata.get("obtained_at"))
            if expires_in_value is not None and obtained_at is not None:
                expires_at = obtained_at + timedelta(seconds=expires_in_value)

        if expires_at is None:
            raw_ts = settings_store.get("ALLEGRO_TOKEN_EXPIRES_AT")
            if raw_ts is not None:
                try:
                    expires_at = datetime.fromtimestamp(float(raw_ts), tz=timezone.utc)
                except (TypeError, ValueError):
                    pass

        if expires_at is None:
            return None

        refresh_at = expires_at - timedelta(seconds=self._margin_seconds)
        now = datetime.now(timezone.utc)
        return (refresh_at - now).total_seconds()

    def _refresh_tokens(self) -> bool:
        refresh_token = settings_store.get("ALLEGRO_REFRESH_TOKEN")
        if not refresh_token:
            LOGGER.debug(
                "Skipping automatic Allegro token refresh because no refresh token is stored",
            )
            ALLEGRO_TOKEN_REFRESH_ATTEMPTS_TOTAL.labels(result="skipped").inc()
            return True

        try:
            payload = allegro_api.refresh_token(refresh_token)
        except HTTPError as exc:
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            LOGGER.warning(
                "Automatic Allegro token refresh failed with HTTP status %s",
                status_code or "unknown",
                exc_info=True,
            )
            ALLEGRO_TOKEN_REFRESH_ATTEMPTS_TOTAL.labels(result="error").inc()
            return False
        except RequestException as exc:
            LOGGER.warning("Automatic Allegro token refresh failed: %s", exc, exc_info=True)
            ALLEGRO_TOKEN_REFRESH_ATTEMPTS_TOTAL.labels(result="error").inc()
            return False
        except Exception:
            LOGGER.exception("Unexpected error while refreshing Allegro tokens automatically")
            ALLEGRO_TOKEN_REFRESH_ATTEMPTS_TOTAL.labels(result="error").inc()
            return False

        access_token = None
        new_refresh_token = refresh_token
        expires_in: Optional[int] = None
        metadata: dict[str, object] = {}
        if isinstance(payload, dict):
            access_token = payload.get("access_token")
            new_refresh_raw = payload.get("refresh_token")
            if new_refresh_raw:
                new_refresh_token = new_refresh_raw
            expires_in = parse_optional_int(payload.get("expires_in"))
            if payload.get("scope"):
                metadata["scope"] = payload["scope"]
            if payload.get("token_type"):
                metadata["token_type"] = payload["token_type"]

        if not access_token:
            LOGGER.error("Automatic Allegro token refresh returned no access token")
            ALLEGRO_TOKEN_REFRESH_ATTEMPTS_TOTAL.labels(result="error").inc()
            return False

        try:
            update_allegro_tokens(access_token, new_refresh_token, expires_in, metadata)
        except SettingsPersistenceError:
            LOGGER.exception(
                "Failed to persist refreshed Allegro tokens; the settings store might be read-only",
            )
            ALLEGRO_TOKEN_REFRESH_ATTEMPTS_TOTAL.labels(result="error").inc()
            return False

        ALLEGRO_TOKEN_REFRESH_ATTEMPTS_TOTAL.labels(result="success").inc()
        ALLEGRO_TOKEN_REFRESH_LAST_SUCCESS.set(time.time())
        LOGGER.info(
            "Successfully refreshed Allegro access token automatically (expires in %s seconds)",
            expires_in if expires_in is not None else "unknown",
        )
        from .print_agent import agent
        agent.reload_config()
        return True

    def _send_token_alert(self, reason: str) -> None:
        """Wyslij powiadomienie Messenger o problemie z tokenem Allegro."""
        try:
            from .notifications.messenger import send_messenger
            message = (
                f"ALLEGRO TOKEN - {reason}\n"
                f"Kolejne bledy: {self._consecutive_failures}\n"
                "Wymagana reczna reautoryzacja w ustawieniach aplikacji."
            )
            sent = send_messenger(message)
            if sent:
                LOGGER.info("Wyslano powiadomienie Messenger o problemie z tokenem Allegro")
            else:
                LOGGER.warning("Nie udalo sie wyslac powiadomienia Messenger o tokenie")
        except Exception:
            LOGGER.exception("Blad wysylania powiadomienia Messenger o tokenie")

    def _track_failure(self, reason: str) -> None:
        """Zlicz kolejny blad i wyslij alert po przekroczeniu progu."""
        self._consecutive_failures += 1
        if (
            self._consecutive_failures >= TOKEN_FAILURE_NOTIFY_THRESHOLD
            and not self._notification_sent
        ):
            self._send_token_alert(reason)
            self._notification_sent = True

    def _reset_failures(self) -> None:
        """Wyzeruj licznik bledow po udanym odswiezeniu."""
        self._consecutive_failures = 0
        self._notification_sent = False

    def _run(self) -> None:
        backoff = self._error_backoff_initial
        _none_logged = False
        while not self._stop_event.is_set():
            seconds_until_refresh = self._seconds_until_refresh()
            if seconds_until_refresh is None:
                if not _none_logged:
                    LOGGER.warning(
                        "Brak tokenow Allegro lub daty wygasania - automatyczne odswiezanie niemozliwe"
                    )
                    _none_logged = True
                self._track_failure("Brak tokenow lub daty wygasania")
                wait_time = self._idle_interval
            elif seconds_until_refresh <= 0:
                _none_logged = False
                if self._refresh_tokens():
                    backoff = self._error_backoff_initial
                    self._reset_failures()
                    continue
                self._track_failure("Nie udalo sie odswiezyc tokenu")
                ALLEGRO_TOKEN_REFRESH_RETRIES_TOTAL.inc()
                wait_time = backoff
                backoff = min(backoff * 2, self._error_backoff_max)
            else:
                _none_logged = False
                self._reset_failures()
                wait_time = min(seconds_until_refresh, self._idle_interval)
            self._stop_event.wait(max(wait_time, 0.01))


token_refresher = AllegroTokenRefresher()

__all__ = ["AllegroTokenRefresher", "token_refresher"]
