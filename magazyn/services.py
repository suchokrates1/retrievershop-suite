from __future__ import annotations

"""Backward compatibility layer for legacy service imports."""

from .db import consume_stock, get_session, record_purchase, record_sale
from .models import Product, ProductSize, PurchaseBatch, Sale
from .domain.inventory import (
    consume_order_stock,
    export_rows,
    get_product_sizes,
    get_products_for_delivery,
    import_from_dataframe,
    record_delivery,
    update_quantity,
)
from .domain.invoice_import import (
    _import_invoice_df,
    _parse_pdf,
    _parse_simple_pdf,
    _parse_tiptop_invoice,
    import_invoice_file,
    import_invoice_rows,
)
from .domain.products import (
    _clean_barcode,
    _to_decimal,
    _to_int,
    create_product,
    delete_product,
    find_by_barcode,
    get_product_details,
    list_products,
    update_product,
)
from .domain.reports import get_sales_summary

__all__ = [
    "consume_order_stock",
    "consume_stock",
    "create_product",
    "delete_product",
    "export_rows",
    "find_by_barcode",
    "get_product_details",
    "get_product_sizes",
    "get_products_for_delivery",
    "get_sales_summary",
    "get_session",
    "import_from_dataframe",
    "import_invoice_file",
    "import_invoice_rows",
    "record_delivery",
    "record_purchase",
    "record_sale",
    "update_product",
    "update_quantity",
    "_clean_barcode",
    "_import_invoice_df",
    "_parse_pdf",
    "_parse_simple_pdf",
    "_parse_tiptop_invoice",
    "_to_decimal",
    "_to_int",
    "Product",
    "ProductSize",
    "PurchaseBatch",
    "Sale",
]
