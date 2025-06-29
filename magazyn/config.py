import os
from types import SimpleNamespace
from dotenv import load_dotenv


def load_config():
    """Load settings from .env and environment variables."""
    load_dotenv()
    return SimpleNamespace(
        API_TOKEN=os.getenv("API_TOKEN"),
        PAGE_ACCESS_TOKEN=os.getenv("PAGE_ACCESS_TOKEN"),
        RECIPIENT_ID=os.getenv("RECIPIENT_ID"),
        STATUS_ID=int(os.getenv("STATUS_ID", "91618")),
        PRINTER_NAME=os.getenv("PRINTER_NAME", "Xprinter"),
        CUPS_SERVER=os.getenv("CUPS_SERVER"),
        CUPS_PORT=os.getenv("CUPS_PORT"),
        POLL_INTERVAL=int(os.getenv("POLL_INTERVAL", "60")),
        QUIET_HOURS_START=os.getenv("QUIET_HOURS_START", "10:00"),
        QUIET_HOURS_END=os.getenv("QUIET_HOURS_END", "22:00"),
        TIMEZONE=os.getenv("TIMEZONE", "Europe/Warsaw"),
        PRINTED_EXPIRY_DAYS=int(os.getenv("PRINTED_EXPIRY_DAYS", "5")),
        LOG_LEVEL=os.getenv("LOG_LEVEL", "INFO").upper(),
        LOG_FILE=os.getenv(
            "LOG_FILE", os.path.join(os.path.dirname(__file__), "agent.log")
        ),
        DB_PATH=os.getenv(
            "DB_PATH", os.path.join(os.path.dirname(__file__), "database.db")
        ),
        SECRET_KEY=os.getenv("SECRET_KEY", "default_secret_key"),
        FLASK_DEBUG=os.getenv("FLASK_DEBUG") == "1",
        DEFAULT_SHIPPING_ALLEGRO=float(os.getenv("DEFAULT_SHIPPING_ALLEGRO", "0")),
        DEFAULT_SHIPPING_VINTED=float(os.getenv("DEFAULT_SHIPPING_VINTED", "0")),
        COMMISSION_ALLEGRO=float(os.getenv("COMMISSION_ALLEGRO", "0")),
        COMMISSION_VINTED=float(os.getenv("COMMISSION_VINTED", "0")),
        LOW_STOCK_THRESHOLD=int(os.getenv("LOW_STOCK_THRESHOLD", "1")),
        ALERT_EMAIL=os.getenv("ALERT_EMAIL"),
        SMTP_SERVER=os.getenv("SMTP_SERVER"),
        SMTP_PORT=os.getenv("SMTP_PORT", "25"),
        SMTP_USERNAME=os.getenv("SMTP_USERNAME"),
        SMTP_PASSWORD=os.getenv("SMTP_PASSWORD"),
    )


settings = load_config()
