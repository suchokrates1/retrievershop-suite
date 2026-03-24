"""
Pakiet wfirma_api - klient API wFirma do wystawiania faktur.

Moduly:
- client: Klient HTTP (auth, retry)
- invoices: Tworzenie faktur VAT, pobieranie PDF
- contractors: Zarzadzanie kontrahentami
"""

from .client import WFirmaClient
from .invoices import create_invoice, download_invoice_pdf
from .contractors import find_contractor, create_contractor, find_or_create_contractor

__all__ = [
    "WFirmaClient",
    "create_invoice",
    "download_invoice_pdf",
    "find_contractor",
    "create_contractor",
    "find_or_create_contractor",
]
