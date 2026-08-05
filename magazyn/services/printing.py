"""Niskopoziomowa obsługa drukowania przez CUPS."""

from __future__ import annotations

import base64
import logging
import os
import re
import subprocess  # nosec B404
import tempfile
import time
from dataclasses import dataclass
from typing import Optional


logger = logging.getLogger(__name__)

_JOB_ID_RE = re.compile(r"request id is (\S+)", re.IGNORECASE)

# Domyślne progi: zdrowy job ~kilka sekund, wolny ale żywy bywa ~1 min.
# Po timeout: cancel + cupsdisable/enable + jeden retry.
_DEFAULT_JOB_TIMEOUT_SECONDS = 120.0
_DEFAULT_POLL_INTERVAL_SECONDS = 2.0
_DEFAULT_MAX_ATTEMPTS = 2


class PrintCommandError(RuntimeError):
    """Błąd wywołania systemowego drukowania."""


class PrintJobTimeoutError(PrintCommandError):
    """Job CUPS nie zakończył się w limicie czasu (zawieszona drukarka/backend)."""


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class CupsPrinter:
    printer_name: str
    cups_server: Optional[str] = None
    cups_port: Optional[int] = None
    job_timeout_seconds: float = _DEFAULT_JOB_TIMEOUT_SECONDS
    poll_interval_seconds: float = _DEFAULT_POLL_INTERVAL_SECONDS
    max_attempts: int = _DEFAULT_MAX_ATTEMPTS
    wait_for_completion: bool = True

    @classmethod
    def from_env(
        cls,
        *,
        printer_name: str,
        cups_server: Optional[str] = None,
        cups_port: Optional[int] = None,
    ) -> "CupsPrinter":
        """Zbuduj drukarkę z opcjonalnymi progami z env."""
        return cls(
            printer_name=printer_name,
            cups_server=cups_server,
            cups_port=cups_port,
            job_timeout_seconds=_env_float(
                "CUPS_JOB_TIMEOUT_SECONDS", _DEFAULT_JOB_TIMEOUT_SECONDS
            ),
            poll_interval_seconds=_env_float(
                "CUPS_JOB_POLL_INTERVAL_SECONDS", _DEFAULT_POLL_INTERVAL_SECONDS
            ),
            max_attempts=max(
                1, _env_int("CUPS_PRINT_MAX_ATTEMPTS", _DEFAULT_MAX_ATTEMPTS)
            ),
        )

    def _host(self) -> Optional[str]:
        if not self.cups_server and not self.cups_port:
            return None
        server = self.cups_server or "localhost"
        return f"{server}:{self.cups_port}" if self.cups_port else server

    def _with_host(self, executable: str, *args: str) -> list[str]:
        cmd = [executable]
        host = self._host()
        if host:
            cmd.extend(["-h", host])
        cmd.extend(args)
        return cmd

    def _command(self, file_path: str) -> list[str]:
        return self._with_host("lp", "-d", self.printer_name, file_path)

    @staticmethod
    def _safe_extension(extension: str | None) -> str:
        return re.sub(r"[^A-Za-z0-9]", "", extension or "") or "pdf"

    def print_label_base64(self, base64_data: str, extension: str | None = "pdf") -> None:
        payload = base64.b64decode(base64_data)
        suffix = f".{self._safe_extension(extension)}"
        file_path = self._write_temp_file(payload, prefix="label_", suffix=suffix)
        try:
            self._print_file(file_path)
        finally:
            self._remove_temp_file(file_path)

    def print_text(self, text: str, *, prefix: str = "print_test_") -> None:
        file_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                prefix=prefix,
                suffix=".txt",
                delete=False,
            ) as handle:
                file_path = handle.name
                handle.write(text)
            self._print_file(file_path)
        finally:
            if file_path:
                self._remove_temp_file(file_path)

    def _print_file(self, file_path: str) -> None:
        attempts = max(1, int(self.max_attempts))
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                self._submit_and_wait(file_path)
                if attempt > 1:
                    logger.info(
                        "CUPS: wydruk OK po retry (attempt=%s/%s, printer=%s)",
                        attempt,
                        attempts,
                        self.printer_name,
                    )
                return
            except PrintJobTimeoutError as exc:
                last_error = exc
                logger.warning(
                    "CUPS: timeout joba (attempt=%s/%s, printer=%s): %s",
                    attempt,
                    attempts,
                    self.printer_name,
                    exc,
                )
                if attempt >= attempts:
                    raise
        if last_error:
            raise last_error

    def _submit_and_wait(self, file_path: str) -> None:
        job_id = self._submit_job(file_path)
        if not self.wait_for_completion:
            return
        if not job_id:
            logger.warning(
                "CUPS: lp nie zwrócił job id (printer=%s) - pomijam wait",
                self.printer_name,
            )
            return
        self._wait_for_job(job_id)

    def _submit_job(self, file_path: str) -> str | None:
        result = self._run(self._command(file_path), check=True)
        return self._parse_job_id(result.stdout.decode(errors="replace"))

    def _wait_for_job(self, job_id: str) -> None:
        timeout = max(1.0, float(self.job_timeout_seconds))
        poll = max(0.2, float(self.poll_interval_seconds))
        deadline = time.monotonic() + timeout
        logger.info(
            "CUPS: czekam na job %s (timeout=%.0fs, printer=%s)",
            job_id,
            timeout,
            self.printer_name,
        )
        while time.monotonic() < deadline:
            if not self._job_is_active(job_id):
                logger.info("CUPS: job %s zakończony", job_id)
                return
            time.sleep(poll)

        logger.error(
            "CUPS: job %s przekroczył timeout %.0fs - recovery + cancel",
            job_id,
            timeout,
        )
        self._recover_stuck_printer(job_id)
        raise PrintJobTimeoutError(
            f"Job {job_id} nie zakończył się w {timeout:.0f}s "
            f"(printer={self.printer_name})"
        )

    def _job_is_active(self, job_id: str) -> bool:
        result = self._run(
            self._with_host("lpstat", "-o", self.printer_name),
            check=False,
        )
        output = result.stdout.decode(errors="replace")
        # lpstat -o listuje aktywne joby; brak job_id = completed/cancelled.
        return job_id in output

    def _recover_stuck_printer(self, job_id: str | None) -> None:
        """Cancel joba i zrestartuj kolejkę (cupsdisable zabija wiszący backend socket)."""
        if job_id:
            self._run(self._with_host("cancel", job_id), check=False)
        self._run(self._with_host("cancel", "-a", self.printer_name), check=False)
        disable = self._run(
            self._with_host("cupsdisable", self.printer_name),
            check=False,
        )
        if disable.returncode != 0:
            logger.warning(
                "CUPS: cupsdisable nieudany (printer=%s): %s",
                self.printer_name,
                disable.stderr.decode(errors="replace").strip(),
            )
        time.sleep(1.0)
        enable = self._run(
            self._with_host("cupsenable", self.printer_name),
            check=False,
        )
        if enable.returncode != 0:
            logger.warning(
                "CUPS: cupsenable nieudany (printer=%s): %s",
                self.printer_name,
                enable.stderr.decode(errors="replace").strip(),
            )
        else:
            logger.info(
                "CUPS: recovery zakończony (cancel + disable/enable, printer=%s)",
                self.printer_name,
            )

    @staticmethod
    def _parse_job_id(stdout: str) -> str | None:
        match = _JOB_ID_RE.search(stdout or "")
        if not match:
            return None
        return match.group(1).rstrip(".")

    def _run(self, cmd: list[str], *, check: bool) -> subprocess.CompletedProcess[bytes]:
        result = subprocess.run(  # nosec B603
            cmd,
            capture_output=True,
            check=False,
        )
        if check and result.returncode != 0:
            message = result.stderr.decode(errors="replace").strip()
            logger.error(
                "Błąd drukowania CUPS (kod %s, cmd=%s): %s",
                result.returncode,
                cmd[0],
                message,
            )
            raise PrintCommandError(message or str(result.returncode))
        return result

    @staticmethod
    def _write_temp_file(payload: bytes, *, prefix: str, suffix: str) -> str:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=prefix,
            suffix=suffix,
            delete=False,
        ) as handle:
            handle.write(payload)
            return handle.name

    @staticmethod
    def _remove_temp_file(file_path: str) -> None:
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except OSError as exc:  # pragma: no cover - defensive cleanup
            logger.debug("Nie udało się usunąć pliku tymczasowego %s: %s", file_path, exc)


__all__ = ["CupsPrinter", "PrintCommandError", "PrintJobTimeoutError"]
