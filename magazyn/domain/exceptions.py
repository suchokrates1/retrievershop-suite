"""Wspolne wyjatki domenowe aplikacji."""

from __future__ import annotations


class DomainError(Exception):
    """Bazowy blad domenowy, ktory mozna mapowac na odpowiedz HTTP."""


class EntityNotFoundError(DomainError):
    """Zasob domenowy nie istnieje."""


class ValidationError(DomainError):
    """Dane wejsciowe nie spelniaja reguly domenowej."""


class ExternalServiceError(DomainError):
    """Zewnetrzna integracja zwrocila blad lub niespojna odpowiedz."""


__all__ = [
    "DomainError",
    "EntityNotFoundError",
    "ExternalServiceError",
    "ValidationError",
]