import os
from types import SimpleNamespace
from dotenv import load_dotenv


def load_config():
    """Load settings from .env and environment variables."""
    load_dotenv()
    excluded = {
        seller.strip()
        for seller in os.getenv("ALLEGRO_EXCLUDED_SELLERS", "").split(",")
        if seller.strip()
    }
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
        FLASK_ENV=os.getenv("FLASK_ENV", "production"),
        COMMISSION_ALLEGRO=float(os.getenv("COMMISSION_ALLEGRO", "0")),
        ALLEGRO_SELLER_ID=os.getenv("ALLEGRO_SELLER_ID"),
        ALLEGRO_EXCLUDED_SELLERS=excluded,
        LOW_STOCK_THRESHOLD=int(os.getenv("LOW_STOCK_THRESHOLD", "1")),
        ALERT_EMAIL=os.getenv("ALERT_EMAIL"),
        SMTP_SERVER=os.getenv("SMTP_SERVER"),
        SMTP_PORT=os.getenv("SMTP_PORT", "25"),
        SMTP_USERNAME=os.getenv("SMTP_USERNAME"),
        SMTP_PASSWORD=os.getenv("SMTP_PASSWORD"),
        ENABLE_MONTHLY_REPORTS=os.getenv("ENABLE_MONTHLY_REPORTS", "1") == "1",
        ENABLE_WEEKLY_REPORTS=os.getenv("ENABLE_WEEKLY_REPORTS", "1") == "1",
        API_RATE_LIMIT_CALLS=int(os.getenv("API_RATE_LIMIT_CALLS", "60")),
        API_RATE_LIMIT_PERIOD=float(os.getenv("API_RATE_LIMIT_PERIOD", "60")),
        API_RETRY_ATTEMPTS=int(os.getenv("API_RETRY_ATTEMPTS", "3")),
        API_RETRY_BACKOFF_INITIAL=float(
            os.getenv("API_RETRY_BACKOFF_INITIAL", "1.0")
        ),
        API_RETRY_BACKOFF_MAX=float(os.getenv("API_RETRY_BACKOFF_MAX", "30.0")),
    )


settings = load_config()
