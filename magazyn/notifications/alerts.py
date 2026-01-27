"""
Modul do wysylania alertow (niski stan magazynowy, email).

Przeniesione ze starego magazyn/notifications.py dla kompatybilnosci.
"""

import logging
import smtplib
from email.message import EmailMessage

from ..config import settings
from .messenger import send_messenger

logger = logging.getLogger(__name__)


def send_email(subject: str, body: str) -> bool:
    """Send an e-mail alert if SMTP settings are provided."""
    if not settings.ALERT_EMAIL or not settings.SMTP_SERVER:
        return False
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.SMTP_USERNAME or "noreply@example.com"
    msg["To"] = settings.ALERT_EMAIL
    msg.set_content(body)
    try:
        with smtplib.SMTP(
            settings.SMTP_SERVER, int(settings.SMTP_PORT or 25)
        ) as smtp:
            if settings.SMTP_USERNAME:
                smtp.login(
                    settings.SMTP_USERNAME, settings.SMTP_PASSWORD or ""
                )
            smtp.send_message(msg)
        logger.info("Alert email sent to %s", settings.ALERT_EMAIL)
        return True
    except Exception as exc:
        logger.error("Email alert failed: %s", exc)
        return False


def send_stock_alert(name: str, size: str, quantity: int) -> None:
    """Notify about low stock via Messenger or email."""
    text = (
        "\u26a0\ufe0f Niski stan: "
        f"{name} ({size}) - pozosta\u0142o {quantity} szt."
    )
    if send_messenger(text):
        return
    send_email("Low stock alert", text)
