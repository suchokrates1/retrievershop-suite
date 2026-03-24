"""
Pakiet wfirma_api - klient API wFirma do wystawiania faktur.

Moduly:
- client: Klient HTTP (auth, retry)
- invoices: Tworzenie faktur VAT, korekt, pobieranie PDF
- contractors: Zarzadzanie kontrahentami
"""

from .client import WFirmaClient
from .invoices import (
    create_invoice,
    create_correction_invoice,
    download_invoice_pdf,
    find_invoice,
    get_invoice,
)
from .contractors import find_contractor, create_contractor, find_or_create_contractor

__all__ = [
    "WFirmaClient",
    "create_invoice",
    "create_correction_invoice",
    "download_invoice_pdf",
    "find_invoice",
    "get_invoice",
    "find_contractor",
    "create_contractor",
    "find_or_create_contractor",
]
