"""Blueprint exposing diagnostics and metrics endpoints."""

from __future__ import annotations

import subprocess
from typing import Dict, Tuple

from flask import Blueprint, Response, current_app, jsonify
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text

from .config import settings
from .db import get_session


bp = Blueprint("diagnostics", __name__)


def _check_database() -> Tuple[str, str]:
    """Run a simple query to ensure the database is reachable."""

    try:
        with get_session() as session:
            session.execute(text("SELECT 1"))
        return "ok", ""
    except Exception as exc:  # pragma: no cover - defensive
        current_app.logger.exception("Database health check failed: %s", exc)
        return "error", str(exc)


def _check_cups() -> Tuple[str, str]:
    """Verify that the configured CUPS server is reachable."""

    host = None
    if settings.CUPS_SERVER or settings.CUPS_PORT:
        host = settings.CUPS_SERVER or "localhost"
        if settings.CUPS_PORT:
            host = f"{host}:{settings.CUPS_PORT}"

    cmd = ["lpstat", "-r"] if not host else ["lpstat", "-h", host, "-r"]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            check=False,
            timeout=5,
        )
    except Exception as exc:  # pragma: no cover - defensive
        current_app.logger.exception("CUPS health check failed: %s", exc)
        return "error", str(exc)

    if result.returncode != 0:
        stderr = result.stderr.decode() if result.stderr else ""
        stdout = result.stdout.decode() if result.stdout else ""
        message = stderr or stdout or "Unknown error"
        current_app.logger.error("CUPS health check returned %s", message)
        return "error", message

    return "ok", ""


@bp.route("/healthz")
def healthz():
    """Return status of dependent services."""

    checks: Dict[str, Tuple[str, str]] = {
        "database": _check_database(),
        "cups": _check_cups(),
    }

    overall = "ok" if all(status == "ok" for status, _ in checks.values()) else "error"
    response = {
        "status": overall,
        "checks": {
            name: {"status": status, "details": detail}
            for name, (status, detail) in checks.items()
        },
    }
    http_status = 200 if overall == "ok" else 503
    return jsonify(response), http_status


@bp.route("/metrics")
def metrics() -> Response:
    """Expose Prometheus metrics."""

    return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)

