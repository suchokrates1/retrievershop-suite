"""
Pakiet blueprintów aplikacji.

Zawiera wyodrebnione blueprinty dla lepszej organizacji kodu.
"""
from .scanning import bp as scanning_bp

__all__ = ['scanning_bp']
