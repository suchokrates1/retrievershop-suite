"""Niezalezne workery wydzielone z glownej petli print agenta.

Kazdy worker dziala we wlasnym watku z izolowana obsluga bledow.
Awaria jednego workera nie wplywa na pozostale ani na glowna
petle drukowania etykiet.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .label_agent import LabelAgent


class BaseWorker:
    """Bazowy worker z wlasnym watkiem i obsluga bledow."""

    def __init__(self, name: str, interval_seconds: float, agent: LabelAgent):
        self.name = name
        self.interval = interval_seconds
        self.agent = agent
        self.logger = logging.getLogger(f"magazyn.worker.{name}")
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._consecutive_errors = 0
        self._max_consecutive_errors = 10
        self._backoff_seconds = 300  # 5 min po serii bledow

    def _run(self) -> None:
        raise NotImplementedError

    def _loop(self) -> None:
        self.logger.info("Worker '%s' uruchomiony (interwal: %ss)", self.name, self.interval)
        while not self._stop_event.is_set():
            try:
                self._run()
                self._consecutive_errors = 0
            except Exception as exc:
                self._consecutive_errors += 1
                self.logger.error(
                    "[%s] Blad (kolejny nr %d): %s",
                    self.name, self._consecutive_errors, exc,
                )
                if self._consecutive_errors >= self._max_consecutive_errors:
                    self.logger.critical(
                        "[%s] %d bledow z rzedu - worker wstrzymany na %ds",
                        self.name, self._consecutive_errors, self._backoff_seconds,
                    )
                    self._stop_event.wait(self._backoff_seconds)
                    self._consecutive_errors = 0
            self._stop_event.wait(self.interval)

    def start(self) -> bool:
        if self._thread and self._thread.is_alive():
            return False
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name=f"worker-{self.name}",
        )
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=10)
            self._thread = None

    @property
    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()


class TrackingWorker(BaseWorker):
    """Sprawdza statusy przesylek przez Allegro Tracking API."""

    def __init__(self, agent: LabelAgent):
        super().__init__("tracking", 900, agent)  # 15 min

    def _run(self) -> None:
        self.agent._check_tracking_statuses()


class MessagingWorker(BaseWorker):
    """Synchronizuje dyskusje i wiadomosci Allegro."""

    def __init__(self, agent: LabelAgent):
        super().__init__("messaging", 300, agent)  # 5 min

    def _run(self) -> None:
        token_valid = (
            hasattr(self.agent.settings, "ALLEGRO_ACCESS_TOKEN")
            and self.agent.settings.ALLEGRO_ACCESS_TOKEN
        )
        expires_at = getattr(self.agent.settings, "ALLEGRO_TOKEN_EXPIRES_AT", 0)

        if not token_valid or expires_at <= time.time():
            self.logger.debug("Token Allegro niedostepny/niewazny - pomijam")
            return

        access_token = self.agent.settings.ALLEGRO_ACCESS_TOKEN
        self.agent._check_allegro_discussions(access_token)
        self.agent._check_allegro_messages(access_token)


class ReportWorker(BaseWorker):
    """Wysyla raporty okresowe (tygodniowe/miesieczne)."""

    def __init__(self, agent: LabelAgent):
        super().__init__("reports", 3600, agent)  # 1h

    def _run(self) -> None:
        self.agent._send_periodic_reports()
