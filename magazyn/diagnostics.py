"""Blueprint exposing diagnostics and metrics endpoints."""

from __future__ import annotations

import subprocess
from typing import Dict, Tuple

from flask import Blueprint, Response, current_app, jsonify, request
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text

from .config import settings
from .notifications import send_messenger
from .csrf_extension import csrf
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


@bp.route("/hooks/baselinker/label_failed", methods=["GET", "POST"])
@csrf.exempt
def baselinker_label_failed():
    """Receive Baselinker webhook when label generation fails."""

    expected = getattr(settings, "BASELINKER_WEBHOOK_TOKEN", None)
    provided = (
        request.args.get("token")
        or request.form.get("token")
        or request.headers.get("X-Webhook-Token")
    )
    if not expected or provided != expected:
        return jsonify({"status": "forbidden"}), 403

    order_id = request.values.get("order_id") or "?"
    courier = request.values.get("courier") or request.values.get("courier_code") or "?"
    package_id = request.values.get("package_id") or "?"
    reason = request.values.get("reason") or request.values.get("message") or "brak etykiety"

    text = (
        "❌ Baselinker: etykieta nie powstała\n"
        f"ID zamówienia: {order_id}\n"
        f"Kurier: {courier}\n"
        f"Paczka: {package_id}\n"
        f"Powód: {reason}"
    )

    send_messenger(text)
    current_app.logger.warning("Baselinker label_failed webhook: %s", text)
    return jsonify({"status": "ok"})

