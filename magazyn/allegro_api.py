"""
Klient Allegro API - kompatybilność wsteczna.

Ten plik re-eksportuje wszystkie funkcje z pakietu allegro_api/ dla
zachowania kompatybilności wstecznej z istniejącym kodem.

Nowy kod powinien importować bezpośrednio z:
    from magazyn.allegro_api import ...
lub z konkretnych modułów:
    from magazyn.allegro_api.auth import get_***REMOVED***
    from magazyn.allegro_api.billing import fetch_billing_entries
"""

# Re-export z pakietu allegro_api dla kompatybilności wstecznej
from .allegro_api import (
    # Core
    AUTH_URL,
    API_BASE_URL,
    DEFAULT_TIMEOUT,
    MAX_RETRY_ATTEMPTS,
    MAX_BACKOFF_SECONDS,
    # Auth
    get_***REMOVED***,
    refresh_token,
    # Offers
    fetch_offers,
    fetch_product_listing,
    # Messaging
    fetch_discussions,
    fetch_message_threads,
    fetch_discussion_issues,
    fetch_discussion_chat,
    fetch_thread_messages,
    send_thread_message,
    send_discussion_message,
    # Billing
    fetch_billing_entries,
    fetch_billing_types,
    get_order_billing_summary,
    # Shipping
    estimate_allegro_shipping_cost,
    ALLEGRO_SMART_THRESHOLDS,
    ALLEGRO_SMART_SHIPPING_COSTS,
    DEFAULT_SHIPPING_COSTS,
    # Attachments
    download_attachment,
    create_attachment_declaration,
    upload_attachment,
    upload_attachment_complete,
    download_issue_attachment,
    create_issue_attachment_declaration,
    upload_issue_attachment,
    upload_issue_attachment_complete,
    # Tracking
    fetch_parcel_tracking,
)

__all__ = [
    "AUTH_URL",
    "API_BASE_URL",
    "DEFAULT_TIMEOUT",
    "MAX_RETRY_ATTEMPTS",
    "MAX_BACKOFF_SECONDS",
    "get_***REMOVED***",
    "refresh_token",
    "fetch_offers",
    "fetch_product_listing",
    "fetch_discussions",
    "fetch_message_threads",
    "fetch_discussion_issues",
    "fetch_discussion_chat",
    "fetch_thread_messages",
    "send_thread_message",
    "send_discussion_message",
    "fetch_billing_entries",
    "fetch_billing_types",
    "get_order_billing_summary",
    "estimate_allegro_shipping_cost",
    "ALLEGRO_SMART_THRESHOLDS",
    "ALLEGRO_SMART_SHIPPING_COSTS",
    "DEFAULT_SHIPPING_COSTS",
    "download_attachment",
    "create_attachment_declaration",
    "upload_attachment",
    "upload_attachment_complete",
    "download_issue_attachment",
    "create_issue_attachment_declaration",
    "upload_issue_attachment",
    "upload_issue_attachment_complete",
    "fetch_parcel_tracking",
]
