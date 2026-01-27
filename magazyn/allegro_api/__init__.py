"""
Pakiet allegro_api - modularny klient API Allegro.

Moduły:
- core: Podstawowe funkcje HTTP, retry logic, rate limiting
- auth: Autoryzacja OAuth, refresh token
- offers: Pobieranie ofert
- messaging: Dyskusje, wątki, wiadomości
- billing: Wpisy billingowe, typy opłat
- shipping: Szacowanie kosztów wysyłki Allegro Smart
- attachments: Obsługa załączników
- tracking: Śledzenie przesyłek
"""

from .core import (
    AUTH_URL,
    API_BASE_URL,
    DEFAULT_TIMEOUT,
    MAX_RETRY_ATTEMPTS,
    MAX_BACKOFF_SECONDS,
)

from .auth import (
    get_access_token,
    refresh_token,
)

from .offers import (
    fetch_offers,
    fetch_product_listing,
)

from .messaging import (
    fetch_discussions,
    fetch_message_threads,
    fetch_discussion_issues,
    fetch_discussion_chat,
    fetch_thread_messages,
    send_thread_message,
    send_discussion_message,
)

from .billing import (
    fetch_billing_entries,
    fetch_billing_types,
    get_order_billing_summary,
)

from .shipping import (
    estimate_allegro_shipping_cost,
    ALLEGRO_SMART_THRESHOLDS,
    ALLEGRO_SMART_SHIPPING_COSTS,
    DEFAULT_SHIPPING_COSTS,
)

from .attachments import (
    download_attachment,
    create_attachment_declaration,
    upload_attachment,
    upload_attachment_complete,
    download_issue_attachment,
    create_issue_attachment_declaration,
    upload_issue_attachment,
    upload_issue_attachment_complete,
)

from .tracking import (
    fetch_parcel_tracking,
)

from .refunds import (
    get_customer_return,
    validate_return_for_refund,
    initiate_refund,
    get_refund_status,
    ALLEGRO_RETURN_STATUS_DELIVERED,
    REFUNDABLE_STATUSES,
)

__all__ = [
    # Core
    "AUTH_URL",
    "API_BASE_URL",
    "DEFAULT_TIMEOUT",
    "MAX_RETRY_ATTEMPTS",
    "MAX_BACKOFF_SECONDS",
    # Auth
    "get_access_token",
    "refresh_token",
    # Offers
    "fetch_offers",
    "fetch_product_listing",
    # Messaging
    "fetch_discussions",
    "fetch_message_threads",
    "fetch_discussion_issues",
    "fetch_discussion_chat",
    "fetch_thread_messages",
    "send_thread_message",
    "send_discussion_message",
    # Billing
    "fetch_billing_entries",
    "fetch_billing_types",
    "get_order_billing_summary",
    # Shipping
    "estimate_allegro_shipping_cost",
    "ALLEGRO_SMART_THRESHOLDS",
    "ALLEGRO_SMART_SHIPPING_COSTS",
    "DEFAULT_SHIPPING_COSTS",
    # Attachments
    "download_attachment",
    "create_attachment_declaration",
    "upload_attachment",
    "upload_attachment_complete",
    "download_issue_attachment",
    "create_issue_attachment_declaration",
    "upload_issue_attachment",
    "upload_issue_attachment_complete",
    # Tracking
    "fetch_parcel_tracking",
    # Refunds
    "get_customer_return",
    "validate_return_for_refund",
    "initiate_refund",
    "get_refund_status",
    "ALLEGRO_RETURN_STATUS_DELIVERED",
    "REFUNDABLE_STATUSES",
]
