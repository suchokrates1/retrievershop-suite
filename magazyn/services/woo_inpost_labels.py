"""Etykiety InPost ShipX dla zamowien WooCommerce (print agent)."""

from __future__ import annotations

import base64
from typing import Any, Dict, List


def get_woo_inpost_packages(agent, order_id: str) -> List[Dict[str, Any]]:
    """Utworz lub pobierz etykiete InPost ShipX dla zamowienia WooCommerce.

    ``shipment_id`` zapisywany jest natychmiast po utworzeniu przesylki
    (przed oczekiwaniem na etykiete), zeby retry agenta nie tworzylo duplikatow.
    """
    from ..inpost_api import InpostShipxError, create_shipment_and_label
    from ..inpost_api.shipx import InpostShipxClient
    from ..woocommerce_api import WooClient, WooClientError
    from ..woocommerce_api.orders import update_order_tracking
    from .print_agent_errors import ApiError

    state_key = f"inpost_shipment:{order_id}"
    stored = agent._load_state_value(state_key)
    order_data = getattr(agent, "last_order_data", None) or {}
    if order_data.get("order_id") != order_id:
        order_data = {"order_id": order_id, **order_data}

    if stored:
        agent.logger.info("Woo %s: pobieram etykiete InPost %s", order_id, stored)
        try:
            label_pdf = InpostShipxClient().get_label_pdf(stored)
        except InpostShipxError as exc:
            raise ApiError(str(exc)) from exc
        return [
            {
                "shipment_id": stored,
                "waybill": order_data.get("delivery_package_nr") or stored,
                "carrier_id": "INPOST",
                "courier_code": "INPOST",
                "courier_package_nr": order_data.get("delivery_package_nr") or stored,
                "label_pdf_b64": base64.b64encode(label_pdf).decode("ascii"),
                "label_ext": "pdf",
            }
        ]

    def _persist_shipment_id(shipment_id: str) -> None:
        agent._save_state_value(state_key, shipment_id)
        agent.logger.info("Woo %s: zapisano InPost shipment_id=%s", order_id, shipment_id)

    try:
        result = create_shipment_and_label(
            order_data,
            on_shipment_created=_persist_shipment_id,
        )
    except InpostShipxError as exc:
        agent.logger.error("InPost ShipX blad dla %s: %s", order_id, exc)
        raise ApiError(str(exc)) from exc

    label_b64 = base64.b64encode(result["label_pdf"]).decode("ascii")

    woo_numeric = str(order_id).removeprefix("woo_")
    try:
        update_order_tracking(
            WooClient(),
            woo_numeric,
            tracking_number=result["waybill"],
            carrier="InPost",
        )
    except (WooClientError, Exception) as exc:
        agent.logger.warning("Nie zaktualizowano trackingu Woo dla %s: %s", order_id, exc)

    return [
        {
            "shipment_id": result["shipment_id"],
            "waybill": result["waybill"],
            "waybills": [result["waybill"]],
            "carrier_id": "INPOST",
            "courier_code": "INPOST",
            "courier_package_nr": result["waybill"],
            "label_pdf_b64": label_b64,
            "label_ext": "pdf",
        }
    ]


__all__ = ["get_woo_inpost_packages"]
