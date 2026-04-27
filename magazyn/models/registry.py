"""Rejestracja wszystkich modulow modeli ORM."""

from __future__ import annotations

from importlib import import_module


MODEL_MODULES = (
    "magazyn.models.allegro",
    "magazyn.models.messages",
    "magazyn.models.orders",
    "magazyn.models.price_reports",
    "magazyn.models.printing",
    "magazyn.models.products",
    "magazyn.models.returns",
    "magazyn.models.settings",
    "magazyn.models.shipments",
    "magazyn.models.stocktakes",
    "magazyn.models.users",
)


def import_all_models() -> None:
    for module_name in MODEL_MODULES:
        import_module(module_name)