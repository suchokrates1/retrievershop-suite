"""Przygotowanie etykiety zamowienia do pobrania."""

from __future__ import annotations

import base64
import tempfile
from dataclasses import dataclass


@dataclass(frozen=True)
class PreparedOrderLabel:
    path: str
    filename: str
    mimetype: str


def prepare_order_label_download(order_id: str, label_agent) -> PreparedOrderLabel | None:
    """Pobierz pierwsza dostepna etykiete zamowienia i zapisz ja do pliku tymczasowego."""
    packages = label_agent.get_order_packages(order_id)
    for package in packages:
        package_id = package.get("shipment_id") or package.get("package_id")
        courier_code = package.get("courier_code") or package.get("carrier_id") or ""
        if not package_id:
            continue

        label_data, extension = label_agent.get_label(courier_code, package_id)
        if not label_data:
            continue

        label_bytes = base64.b64decode(label_data)
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=f".{extension}")
        temp_file.write(label_bytes)
        temp_file.close()
        return PreparedOrderLabel(
            path=temp_file.name,
            filename=f"etykieta_{order_id}.{extension}",
            mimetype="application/pdf" if extension == "pdf" else "application/octet-stream",
        )
    return None


__all__ = ["PreparedOrderLabel", "prepare_order_label_download"]