"""Wspolne wyjatki agenta drukowania."""

from __future__ import annotations


class ApiError(Exception):
    """Raised when an API call fails."""


class PrintError(Exception):
    """Raised when sending data to the printer fails."""


class ShipmentExpiredError(ApiError):
    """Przesylka wygasla/anulowana - wymaga ponownego utworzenia."""

    def __init__(self, shipment_id: str, message: str = ""):
        self.shipment_id = shipment_id
        super().__init__(message or f"Przesylka {shipment_id} wygasla (403)")


__all__ = ["ApiError", "PrintError", "ShipmentExpiredError"]