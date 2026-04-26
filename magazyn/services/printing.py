"""Niskopoziomowa obsługa drukowania przez CUPS."""

from __future__ import annotations

import base64
import logging
import os
import re
import subprocess  # nosec B404
import tempfile
from dataclasses import dataclass
from typing import Optional


logger = logging.getLogger(__name__)


class PrintCommandError(RuntimeError):
    """Błąd wywołania systemowego drukowania."""


@dataclass(frozen=True)
class CupsPrinter:
    printer_name: str
    cups_server: Optional[str] = None
    cups_port: Optional[int] = None

    def _host(self) -> Optional[str]:
        if not self.cups_server and not self.cups_port:
            return None
        server = self.cups_server or "localhost"
        return f"{server}:{self.cups_port}" if self.cups_port else server

    def _command(self, file_path: str) -> list[str]:
        cmd = ["lp"]
        host = self._host()
        if host:
            cmd.extend(["-h", host])
        cmd.extend(["-d", self.printer_name, file_path])
        return cmd

    @staticmethod
    def _safe_extension(extension: str | None) -> str:
        return re.sub(r"[^A-Za-z0-9]", "", extension or "") or "pdf"

    def print_label_base64(self, base64_data: str, extension: str | None = "pdf") -> None:
        payload = base64.b64decode(base64_data)
        suffix = f".{self._safe_extension(extension)}"
        file_path = self._write_temp_file(payload, prefix="label_", suffix=suffix)
        try:
            self._run_lp(file_path)
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
            self._run_lp(file_path)
        finally:
            if file_path:
                self._remove_temp_file(file_path)

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

    def _run_lp(self, file_path: str) -> None:
        result = subprocess.run(  # nosec B603
            self._command(file_path),
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            message = result.stderr.decode(errors="replace").strip()
            logger.error("Błąd drukowania CUPS (kod %s): %s", result.returncode, message)
            raise PrintCommandError(message or str(result.returncode))

    @staticmethod
    def _remove_temp_file(file_path: str) -> None:
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except OSError as exc:  # pragma: no cover - defensive cleanup
            logger.debug("Nie udało się usunąć pliku tymczasowego %s: %s", file_path, exc)


__all__ = ["CupsPrinter", "PrintCommandError"]