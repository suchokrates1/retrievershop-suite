"""Operacje na etykietach wysylkowych zamowien."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..db import get_session
from .order_status import add_order_status


@dataclass(frozen=True)
class LabelActionResult:
    message: str
    category: str
    printed: bool = False


def reprint_order_labels(order_id: str, print_agent_module: Any | None = None) -> LabelActionResult:
    if print_agent_module is None:
        from .. import print_agent as print_agent_module

    packages = print_agent_module.get_order_packages(order_id)
    printed_any = False

    for package in packages:
        package_id = package.get("shipment_id") or package.get("package_id")
        courier_code = package.get("courier_code") or package.get("carrier_id") or ""
        if not package_id:
            continue
        label_data, extension = print_agent_module.get_label(courier_code, package_id)
        if label_data:
            print_agent_module.print_label(label_data, extension, order_id)
            printed_any = True

    if not printed_any:
        return LabelActionResult("Nie znaleziono etykiety do wydruku", "warning")

    with get_session() as db:
        add_order_status(db, order_id, "wydrukowano", notes="Reprint etykiety")
        db.commit()

    return LabelActionResult(
        "Etykieta została wysłana do drukarki",
        "success",
        printed=True,
    )


__all__ = ["LabelActionResult", "reprint_order_labels"]