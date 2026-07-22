"""Publiczne API sklepu WP (trust, mail, katalog)."""

from .mail_api import bp as mail_bp
from .trust_api import bp as trust_bp

__all__ = ["mail_bp", "trust_bp"]
