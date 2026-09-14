"""Publiczne helpery śledzenia przesyłek."""

from __future__ import annotations

import logging
from typing import Optional
from urllib.parse import quote_plus


logger = logging.getLogger(__name__)

TRACKING_URL_TEMPLATES: dict[str, Optional[str]] = {
    "inpost": "https://inpost.pl/sledzenie-przesylek?number={tracking_number}",
    "paczkomat": "https://inpost.pl/sledzenie-przesylek?number={tracking_number}",
    "dpd": "https://tracktrace.dpd.com.pl/parcelDetails?typ=1&p1={tracking_number}",
    "pocztex": "https://emonitoring.poczta-polska.pl/?numer={tracking_number}",
    "poczta": "https://emonitoring.poczta-polska.pl/?numer={tracking_number}",
    "dhl": "https://www.dhl.com/pl-pl/home/tracking.html?tracking-id={tracking_number}",
    "ups": "https://www.ups.com/track?tracknum={tracking_number}",
    "fedex": "https://www.fedex.com/fedextrack/?tracknumbers={tracking_number}",
    "gls": "https://gls-group.com/PL/pl/sledzenie-paczek?match={tracking_number}",
    "orlen": None,
    "allegro": None,
}


def get_tracking_url(
    courier_code: Optional[str],
    delivery_package_module: Optional[str],
    tracking_number: Optional[str],
    delivery_method: Optional[str] = None,
) -> Optional[str]:
    """Zbuduj publiczny URL śledzenia przesyłki, jeśli przewoźnik go udostępnia."""
    if not tracking_number:
        return None

    courier_text = f"{courier_code or ''} {delivery_package_module or ''} {delivery_method or ''}".lower()
    encoded_tracking_number = quote_plus(str(tracking_number))
    logger.debug(
        "get_tracking_url: courier_text=%r tracking_number=%s",
        courier_text,
        tracking_number,
    )

    for key, template in TRACKING_URL_TEMPLATES.items():
        if key in courier_text:
            logger.debug(
                "get_tracking_url: matched %r -> %s",
                key,
                template or "NO_PUBLIC_URL",
            )
            return template.format(tracking_number=encoded_tracking_number) if template else None

    logger.debug("get_tracking_url: no match for courier_text=%r", courier_text)
    return None


__all__ = ["TRACKING_URL_TEMPLATES", "get_tracking_url"]