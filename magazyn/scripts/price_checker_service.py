#!/usr/bin/env python3
"""Automated Allegro Price Checker Service.

Runs as a standalone service (cron/systemd/Docker) to check competitor prices
and send notifications via Messenger. Designed to run on minipc.

Features:
- Checks prices every N days (default: 2)
- Excludes Chinese/blacklisted sellers
- Sends Messenger notifications only during business hours
- Saves competitor data (price, seller, URL) to database
"""

import logging
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Optional

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from magazyn.config import settings
from magazyn.db import get_session, configure_engine
from magazyn.models import AllegroOffer, ProductSize, AllegroPriceHistory

# Initialize database connection
configure_engine(settings.DB_PATH)
from magazyn.notifications import send_messenger

# Use Camoufox scraper (better anti-detection than Selenium)
# Falls back to Selenium if Camoufox not available
try:
    from magazyn.camoufox_scraper import (
        fetch_competitors_for_offer_camoufox as fetch_competitors_for_offer,
        parse_price_amount,
    )
    SCRAPER_ENGINE = "camoufox"
except ImportError:
    from magazyn.allegro_scraper import (
        fetch_competitors_for_offer,
        parse_price_amount,
    )
    SCRAPER_ENGINE = "selenium"

class AllegroScrapeError(RuntimeError):
    """Scraping error with logs."""
    def __init__(self, message: str, logs: list = None):
        super().__init__(message)
        self.logs = logs or []

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("price_checker.log"),
    ],
)
logger = logging.getLogger(__name__)

logger.info("Price checker using scraper engine: %s", SCRAPER_ENGINE)


# =============================================================================
# Configuration
# =============================================================================

# Check interval in days (default: 2)
CHECK_INTERVAL_DAYS = int(os.environ.get("PRICE_CHECK_INTERVAL_DAYS", "2"))

# Block images to save bandwidth (Camoufox only)
BLOCK_IMAGES = os.environ.get("SCRAPER_BLOCK_IMAGES", "1").lower() in ("1", "true", "yes")

# Business hours for notifications (QUIET_HOURS are when we DON'T send)
# Based on .env: QUIET_HOURS_START=10:00, QUIET_HOURS_END=22:00
# This means notifications are allowed between 10:00 and 22:00
NOTIFY_HOURS_START = int(os.environ.get("NOTIFY_HOURS_START", "10"))
NOTIFY_HOURS_END = int(os.environ.get("NOTIFY_HOURS_END", "22"))

# Chinese/blacklisted seller patterns
EXCLUDED_SELLER_PATTERNS = [
    "aliexpress",
    "alibaba",
    "wish",
    "banggood",
    "gearbest",
    "tomtop",
    "lightinthebox",
    "miniinthebox",
    "dealextreme",
    "dx.com",
    "focalprice",
    "chinavasion",
    "pandawill",
    "tmart",
    "tinydeal",
    "lightake",
    "fasttech",
    "geekbuying",
    "everbuying",
    "sammydress",
    "rosewholesale",
    "newchic",
    "zaful",
    "romwe",
    "shein",
    "patpat",
    "joom",
    "temu",
    # Common Chinese store name patterns
    "_cn",
    "_china",
    "cn_",
    "china_",
    "chinese",
    "chiński",
    "chiny",
]

# Additional excluded sellers from environment (comma-separated)
EXTRA_EXCLUDED = os.environ.get("ALLEGRO_EXCLUDED_SELLERS", "").strip()
if EXTRA_EXCLUDED:
    EXCLUDED_SELLER_PATTERNS.extend(
        [s.strip().lower() for s in EXTRA_EXCLUDED.split(",") if s.strip()]
    )


# =============================================================================
# Helper Functions
# =============================================================================

def is_excluded_seller(seller_name: str) -> bool:
    """Check if seller should be excluded (Chinese/blacklisted)."""
    if not seller_name:
        return False
    seller_lower = seller_name.lower()
    for pattern in EXCLUDED_SELLER_PATTERNS:
        if pattern in seller_lower:
            logger.debug("Excluding seller '%s' (matched pattern: %s)", seller_name, pattern)
            return True
    return False


def is_notification_time() -> bool:
    """Check if current time is within business hours for notifications."""
    try:
        import zoneinfo
        tz = zoneinfo.ZoneInfo(settings.TIMEZONE or "Europe/Warsaw")
    except Exception:
        from datetime import timezone as tz_module
        tz = tz_module(timedelta(hours=1))  # CET fallback
    
    now = datetime.now(tz)
    current_hour = now.hour
    
    # Allow notifications between NOTIFY_HOURS_START and NOTIFY_HOURS_END
    if NOTIFY_HOURS_START <= current_hour < NOTIFY_HOURS_END:
        return True
    
    logger.debug(
        "Outside notification hours: %d (allowed: %d-%d)",
        current_hour, NOTIFY_HOURS_START, NOTIFY_HOURS_END
    )
    return False


def format_price_alert_message(alerts: list[dict]) -> str:
    """Format the Messenger alert message.
    
    Format: "Jesteś droższa w X ofertach:
    - nazwa: twoja cena → ich cena (sprzedawca)
    """
    if not alerts:
        return ""
    
    lines = [f"⚠️ Jesteś droższa w {len(alerts)} ofertach:"]
    for alert in alerts:
        line = (
            f"• {alert['name']}: {alert['our_price']:.2f} zł → "
            f"{alert['their_price']:.2f} zł ({alert['seller']})"
        )
        lines.append(line)
    
    return "\n".join(lines)


# =============================================================================
# Main Price Checking Logic
# =============================================================================

def check_all_prices() -> dict:
    """Check all Allegro offers for lower competitor prices.
    
    Returns dict with:
    - checked: number of offers checked
    - alerts: list of price alerts
    - errors: number of scraping errors
    """
    alerts: list[dict] = []
    errors = 0
    checked = 0
    
    with get_session() as session:
        # Get all active offers with product info
        rows = (
            session.query(AllegroOffer, ProductSize)
            .join(ProductSize, AllegroOffer.product_size_id == ProductSize.id)
            .filter(AllegroOffer.publication_status == "ACTIVE")
            .all()
        )
        
        logger.info("Found %d active offers to check", len(rows))
        
        for offer, product_size in rows:
            offer_id = offer.offer_id
            our_price = offer.price
            offer_name = offer.title or f"Oferta {offer_id}"
            
            if not offer_id or our_price is None:
                continue
            
            checked += 1
            logger.info("Checking offer %s: %s (%.2f zł)", offer_id, offer_name, our_price)
            
            try:
                # Fetch competitor offers
                # Camoufox version supports block_images, Selenium version ignores it
                scraper_kwargs = {
                    "offer_id": offer_id,
                    "stop_seller": settings.ALLEGRO_SELLER_NAME,
                    "limit": 20,
                    "headless": True,
                }
                if SCRAPER_ENGINE == "camoufox":
                    scraper_kwargs["block_images"] = BLOCK_IMAGES
                
                competitor_offers, logs = fetch_competitors_for_offer(**scraper_kwargs)
                
                # Log scraper output
                for log_entry in logs:
                    logger.debug("Scraper [%s]: %s", offer_id, log_entry)
                
            except AllegroScrapeError as exc:
                logger.error("Scrape failed for %s: %s", offer_id, exc)
                errors += 1
                continue
            except Exception as exc:
                logger.error("Unexpected error for %s: %s", offer_id, exc)
                errors += 1
                continue
            
            # Filter and find lowest price from non-excluded sellers
            lowest_price: Optional[Decimal] = None
            lowest_seller: Optional[str] = None
            lowest_url: Optional[str] = None
            
            for comp_offer in competitor_offers:
                seller_name = (comp_offer.seller or "").strip()
                
                # Skip our own listings
                if (
                    settings.ALLEGRO_SELLER_NAME
                    and seller_name.lower() == settings.ALLEGRO_SELLER_NAME.lower()
                ):
                    continue
                
                # Skip excluded (Chinese) sellers
                if is_excluded_seller(seller_name):
                    continue
                
                price_value = parse_price_amount(comp_offer.price)
                if price_value is None:
                    continue
                
                if lowest_price is None or price_value < lowest_price:
                    lowest_price = price_value
                    lowest_seller = seller_name
                    lowest_url = comp_offer.url
            
            # Record competitor data in database
            if lowest_price is not None:
                timestamp = datetime.now(timezone.utc).isoformat()
                
                # Update existing history or create new entry
                history_entry = AllegroPriceHistory(
                    offer_id=offer_id,
                    product_size_id=product_size.id,
                    price=our_price,
                    recorded_at=timestamp,
                    competitor_price=lowest_price,
                    competitor_seller=lowest_seller,
                    competitor_url=lowest_url,
                )
                session.add(history_entry)
                
                logger.info(
                    "Offer %s: our price %.2f, lowest competitor %.2f (%s)",
                    offer_id, our_price, lowest_price, lowest_seller
                )
                
                # Check if we're more expensive
                if lowest_price < our_price:
                    alerts.append({
                        "offer_id": offer_id,
                        "name": offer_name[:50],  # Truncate long names
                        "our_price": our_price,
                        "their_price": lowest_price,
                        "seller": lowest_seller or "?",
                        "url": lowest_url,
                    })
            
            # Small delay between requests to be nice
            time.sleep(2)
        
        session.commit()
    
    return {
        "checked": checked,
        "alerts": alerts,
        "errors": errors,
    }


def send_price_alerts(alerts: list[dict]) -> bool:
    """Send price alert notification via Messenger if within business hours."""
    if not alerts:
        logger.info("No price alerts to send")
        return True
    
    if not is_notification_time():
        logger.info(
            "Skipping notification - outside business hours. "
            "%d alerts will be sent during next business hours check.",
            len(alerts)
        )
        # TODO: Queue alerts for later? For now we just log them
        return False
    
    message = format_price_alert_message(alerts)
    logger.info("Sending Messenger alert:\n%s", message)
    
    success = send_messenger(message)
    if success:
        logger.info("Messenger alert sent successfully")
    else:
        logger.error("Failed to send Messenger alert")
    
    return success


def run_price_check():
    """Run a single price check cycle."""
    logger.info("=" * 60)
    logger.info("Starting price check at %s", datetime.now().isoformat())
    logger.info("=" * 60)
    
    try:
        result = check_all_prices()
        
        logger.info(
            "Price check complete: %d checked, %d alerts, %d errors",
            result["checked"],
            len(result["alerts"]),
            result["errors"],
        )
        
        if result["alerts"]:
            send_price_alerts(result["alerts"])
        
    except Exception as exc:
        logger.exception("Price check failed: %s", exc)
        # Try to send error notification
        try:
            if is_notification_time():
                send_messenger(f"❌ Price checker error: {exc}")
        except Exception:
            pass


def run_service():
    """Run the price checker as a continuous service."""
    logger.info("Starting Price Checker Service")
    logger.info("Check interval: %d days", CHECK_INTERVAL_DAYS)
    logger.info("Notification hours: %d:00 - %d:00", NOTIFY_HOURS_START, NOTIFY_HOURS_END)
    logger.info("Excluded seller patterns: %d", len(EXCLUDED_SELLER_PATTERNS))
    
    interval_seconds = CHECK_INTERVAL_DAYS * 24 * 60 * 60
    
    while True:
        run_price_check()
        
        next_run = datetime.now() + timedelta(seconds=interval_seconds)
        logger.info("Next check scheduled at: %s", next_run.isoformat())
        
        time.sleep(interval_seconds)


# =============================================================================
# CLI Entry Point
# =============================================================================

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Allegro Price Checker Service")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run once and exit (for cron jobs)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )
    args = parser.parse_args()
    
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    
    if args.once:
        run_price_check()
    else:
        run_service()
