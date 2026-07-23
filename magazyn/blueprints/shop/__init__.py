"""Publiczne API sklepu WP (trust, mail, katalog)."""

from .invoice_api import bp as invoice_bp
from .mail_api import bp as mail_bp
from .return_instructions_api import bp as return_instructions_bp
from .trust_api import bp as trust_bp

__all__ = ["mail_bp", "trust_bp", "return_instructions_bp", "invoice_bp"]
