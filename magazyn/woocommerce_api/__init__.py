"""Klient WooCommerce REST API."""

from .attributes import build_product_attributes, ensure_attribute, ensure_attribute_term
from .categories import ensure_product_category, resolve_category_name
from .client import WooClient, WooClientError
from .media import (
    find_media_id_by_filename,
    get_product_image_ids,
    upload_product_image_from_url,
)
from .orders import fetch_order, fetch_orders, parse_woo_order_to_data, update_order_tracking
from .payments import (
    classify_woo_payment_method,
    estimate_woo_payment_fee,
    get_order_payment_fees,
)
from .products import (
    create_or_update_variable_product,
    find_product_by_ean,
    upsert_variation,
)

__all__ = [
    "WooClient",
    "WooClientError",
    "build_product_attributes",
    "classify_woo_payment_method",
    "create_or_update_variable_product",
    "ensure_attribute",
    "ensure_attribute_term",
    "ensure_product_category",
    "estimate_woo_payment_fee",
    "fetch_order",
    "fetch_orders",
    "find_media_id_by_filename",
    "find_product_by_ean",
    "get_order_payment_fees",
    "get_product_image_ids",
    "parse_woo_order_to_data",
    "resolve_category_name",
    "update_order_tracking",
    "upload_product_image_from_url",
    "upsert_variation",
]
