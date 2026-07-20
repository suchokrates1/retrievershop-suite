"""Klient WooCommerce REST API."""

from .attributes import build_product_attributes, ensure_attribute, ensure_attribute_term
from .categories import ensure_product_category, resolve_category_name
from .client import WooClient, WooClientError
from .orders import fetch_order, fetch_orders, parse_woo_order_to_data, update_order_tracking
from .products import (
    create_or_update_variable_product,
    find_product_by_ean,
    upload_product_image_from_url,
)

__all__ = [
    "WooClient",
    "WooClientError",
    "build_product_attributes",
    "create_or_update_variable_product",
    "ensure_attribute",
    "ensure_attribute_term",
    "ensure_product_category",
    "fetch_order",
    "fetch_orders",
    "find_product_by_ean",
    "parse_woo_order_to_data",
    "resolve_category_name",
    "update_order_tracking",
    "upload_product_image_from_url",
]
