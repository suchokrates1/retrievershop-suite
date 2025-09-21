"""Helpers for loading and persisting configuration values from ``.env`` files."""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from typing import Callable, Iterable, Mapping, MutableMapping, Optional

from dotenv import dotenv_values

ROOT_DIR = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT_DIR / ".env"
EXAMPLE_PATH = ROOT_DIR / ".env.example"

# Settings that should not be editable from the administration panels.
HIDDEN_KEYS = {"ENABLE_HTTP_SERVER", "HTTP_PORT", "DB_PATH"}


def _handle_error(
    error: Exception,
    *,
    logger: Optional[Callable[[str, Exception], None]] = None,
    on_error: Optional[Callable[[str], None]] = None,
    message: str,
) -> None:
    if logger is not None:
        logger(message, error)
    if on_error is not None:
        on_error(message)


def _load_values(path: Path) -> Mapping[str, str]:
    try:
        return dotenv_values(path)
    except Exception:  # pragma: no cover - defensive
        # ``dotenv_values`` already swallows many errors and returns an empty dict
        # but keep the behaviour explicit for clarity.
        return {}


def load_settings(
    *,
    include_hidden: bool = False,
    example_path: Path = EXAMPLE_PATH,
    env_path: Path = ENV_PATH,
    logger: Optional[Callable[[str, Exception], None]] = None,
    on_error: Optional[Callable[[str], None]] = None,
) -> "OrderedDict[str, str]":
    """Return merged configuration values from ``.env`` files.

    The values are based on ``.env.example`` for ordering and fall back to
    ``.env`` when present. Unknown keys from the current ``.env`` file are
    appended to the end of the ordered dictionary.
    """

    if not example_path.exists():
        _handle_error(
            FileNotFoundError(example_path),
            logger=logger,
            on_error=on_error,
            message=f"Settings template missing: {example_path}",
        )
        return OrderedDict()

    try:
        example = _load_values(example_path)
        current = _load_values(env_path) if env_path.exists() else {}
    except Exception as exc:  # pragma: no cover - defensive
        _handle_error(
            exc,
            logger=logger,
            on_error=on_error,
            message=f"Failed to load .env files: {exc}",
        )
        return OrderedDict()

    values: "OrderedDict[str, str]" = OrderedDict()

    for key in example.keys():
        values[key] = current.get(key, example[key])

    for key, val in current.items():
        if key not in values:
            values[key] = val

    if not include_hidden:
        for hidden in HIDDEN_KEYS:
            values.pop(hidden, None)

    return values


def write_env(
    values: Mapping[str, str],
    *,
    example_path: Path = EXAMPLE_PATH,
    env_path: Path = ENV_PATH,
    logger: Optional[Callable[[str, Exception], None]] = None,
    on_error: Optional[Callable[[str], None]] = None,
) -> bool:
    """Persist ``values`` to the ``.env`` file and return success status."""

    try:
        example = _load_values(example_path)
        example_keys = list(example.keys())
        current = _load_values(env_path) if env_path.exists() else {}
        ordered_keys: Iterable[str] = example_keys + [
            key for key in values.keys() if key not in example_keys
        ]
    except Exception as exc:  # pragma: no cover - defensive
        _handle_error(
            exc,
            logger=logger,
            on_error=on_error,
            message=f"Failed to read env template: {exc}",
        )
        return False

    try:
        with env_path.open("w", encoding="utf-8") as handle:
            for key in ordered_keys:
                val = values.get(key, current.get(key, example.get(key, "")))
                handle.write(f"{key}={val}\n")
    except Exception as exc:  # pragma: no cover - defensive
        _handle_error(
            exc,
            logger=logger,
            on_error=on_error,
            message=f"Failed to write .env file: {exc}",
        )
        return False

    try:
        env_path.chmod(0o600)
    except (AttributeError, NotImplementedError, OSError, PermissionError) as exc:
        if logger is not None:
            logger("Failed to set permissions", exc)

    return True


__all__ = [
    "ENV_PATH",
    "EXAMPLE_PATH",
    "HIDDEN_KEYS",
    "load_settings",
    "write_env",
]

