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


class IncompleteReceiverData(Exception):
    """Dane odbiorcy niekompletne - czekamy na Allegro zamiast blad_druku."""

    def __init__(self, order_id: str, reason: str = ""):
        self.order_id = order_id
        self.reason = reason or "brak telefonu/imienia/adresu"
        super().__init__(f"Incomplete receiver data for {order_id}: {self.reason}")


__all__ = ["ApiError", "PrintError", "ShipmentExpiredError", "IncompleteReceiverData"]