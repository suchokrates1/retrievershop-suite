"""Wspolne prymitywy runtime dla agentow i schedulerow."""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timedelta
from typing import Any, Callable, Optional

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None


class BackgroundThreadRuntime:
    """Minimalny wrapper na start/stop pojedynczego watku z Event stopu."""

    def __init__(
        self,
        *,
        name: str,
        logger: logging.Logger,
        join_timeout: float = 5,
    ):
        self.name = name
        self.logger = logger
        self.join_timeout = join_timeout
        self.stop_event = threading.Event()
        self.thread: Optional[threading.Thread] = None

    def is_running(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def start(
        self,
        target: Callable[..., Any],
        *args: Any,
        already_running_message: str,
        started_message: str,
    ) -> bool:
        if self.is_running():
            self.logger.warning(already_running_message)
            return False

        self.stop_event.clear()
        self.thread = threading.Thread(
            target=target,
            args=args,
            daemon=True,
            name=self.name,
        )
        self.thread.start()
        self.logger.info(started_message)
        return True

    def stop(
        self,
        *,
        stopping_message: str,
        stopped_message: str,
    ) -> bool:
        if not self.is_running():
            return False

        self.logger.info(stopping_message)
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=self.join_timeout)
        self.thread = None
        self.logger.info(stopped_message)
        return True


class HeartbeatFileLock:
    """Plikowa blokada z heartbeat, odporna na osierocone locki."""

    def __init__(
        self,
        *,
        lock_file_provider: Callable[[], str],
        poll_interval_provider: Callable[[], int | float],
        logger: logging.Logger,
        stale_warning: str,
        now: Callable[[], datetime] = datetime.now,
    ):
        self.lock_file_provider = lock_file_provider
        self.poll_interval_provider = poll_interval_provider
        self.logger = logger
        self.stale_warning = stale_warning
        self.now = now
        self.lock_handle: Any = None

    @property
    def lock_file(self) -> str:
        return self.lock_file_provider()

    @property
    def heartbeat_path(self) -> str:
        return f"{self.lock_file}.heartbeat"

    def read_heartbeat(self) -> Optional[datetime]:
        try:
            with open(self.heartbeat_path, "r", encoding="utf-8") as handle:
                raw = handle.read().strip()
        except OSError:
            return None
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return None

    def write_heartbeat(self) -> None:
        try:
            with open(self.heartbeat_path, "w", encoding="utf-8") as handle:
                handle.write(self.now().isoformat())
        except OSError as exc:  # pragma: no cover - best effort logging only
            self.logger.debug("Nie mozna zapisac heartbeat: %s", exc)

    def clear_heartbeat(self) -> None:
        try:
            os.remove(self.heartbeat_path)
        except OSError:
            pass

    def cleanup_orphaned_lock(self) -> None:
        heartbeat = self.read_heartbeat()
        if heartbeat is None:
            return

        grace = max(1, self.poll_interval_provider())
        max_age = timedelta(seconds=grace * 4)
        if self.now() - heartbeat <= max_age:
            return

        try:
            with open(self.lock_file, "a+", encoding="utf-8") as handle:
                try:
                    if fcntl:
                        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError:
                    return
        except OSError:
            self.clear_heartbeat()
            return

        try:
            os.remove(self.lock_file)
        except OSError:
            pass
        else:
            self.logger.warning(self.stale_warning)
        self.clear_heartbeat()

    def acquire(self) -> bool:
        self.cleanup_orphaned_lock()
        if self.lock_handle is not None:
            return True

        try:
            self.lock_handle = open(self.lock_file, "w")
            if fcntl:
                fcntl.flock(self.lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            if self.lock_handle:
                self.lock_handle.close()
            self.lock_handle = None
            return False

        self.write_heartbeat()
        return True

    def release(self) -> None:
        self.clear_heartbeat()
        if self.lock_handle:
            try:
                if fcntl:
                    fcntl.flock(self.lock_handle, fcntl.LOCK_UN)
            except OSError:  # pragma: no cover - defensive
                pass
            self.lock_handle.close()
            self.lock_handle = None

        try:
            os.remove(self.lock_file)
        except OSError:
            pass


__all__ = ["BackgroundThreadRuntime", "HeartbeatFileLock"]