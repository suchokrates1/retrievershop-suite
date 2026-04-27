"""Helpery logistyczne API statystyk."""

from __future__ import annotations

from ..models.orders import Order


def build_alerts(
    *,
    returns_rate: float | None = None,
    refund_rate: float | None = None,
    lead_time_hours: float | None = None,
) -> list[dict]:
    alerts: list[dict] = []
    if returns_rate is not None and returns_rate > 8.0:
        alerts.append(
            {
                "code": "RETURNS_RATE_HIGH",
                "level": "warning",
                "message": "Wskaznik zwrotow przekracza prog 8%",
                "value": returns_rate,
                "threshold": 8.0,
            }
        )
    if refund_rate is not None and refund_rate < 80.0:
        alerts.append(
            {
                "code": "REFUND_RATE_LOW",
                "level": "warning",
                "message": "Skutecznosc refundow jest ponizej progu 80%",
                "value": refund_rate,
                "threshold": 80.0,
            }
        )
    if lead_time_hours is not None and lead_time_hours > 48.0:
        alerts.append(
            {
                "code": "LEAD_TIME_HIGH",
                "level": "critical",
                "message": "Sredni lead time przekracza 48h",
                "value": lead_time_hours,
                "threshold": 48.0,
            }
        )
    return alerts


def carrier_label(order: Order) -> str:
    raw_values = [
        (order.courier_code or "").strip(),
        (order.delivery_package_module or "").strip(),
        (order.delivery_method or "").strip(),
    ]
    combined = " ".join(value.lower() for value in raw_values if value)
    if "inpost" in combined or "paczkomat" in combined:
        return "InPost"
    if "dpd" in combined:
        return "DPD"
    if "dhl" in combined:
        return "DHL"
    if "poczta" in combined or "pocztex" in combined:
        return "Poczta Polska"
    if "gls" in combined:
        return "GLS"
    if "ups" in combined:
        return "UPS"
    if "fedex" in combined:
        return "FedEx"
    if "orlen" in combined:
        return "Orlen"
    if "allegro" in combined and "one" in combined:
        return "Allegro One"

    for value in raw_values:
        if value:
            return value
    return "Nieznany"


def delivery_method_label(order: Order) -> str:
    return (
        (order.delivery_method or "").strip()
        or (order.delivery_package_module or "").strip()
        or carrier_label(order)
    )


def group_logistics_rows(rows: dict[str, dict[str, object]]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for row in rows.values():
        lead_times = [float(value) for value in row.pop("lead_times", [])]
        delivered_total = int(row.get("delivered_total", 0) or 0)
        on_time_rate = (
            sum(1 for value in lead_times if value <= 48.0) / delivered_total * 100
            if delivered_total
            else 0.0
        )
        avg_lead = sum(lead_times) / len(lead_times) if lead_times else 0.0
        result.append(
            {
                **row,
                "avg_lead_time_hours": round(avg_lead, 2),
                "on_time_rate_48h": round(on_time_rate, 2),
            }
        )

    result.sort(
        key=lambda item: (
            -int(item.get("shipped_total", 0) or 0),
            float(item.get("avg_lead_time_hours", 0.0) or 0.0),
            str(item.get("carrier", item.get("delivery_method", ""))),
        )
    )
    return result


__all__ = [
    "build_alerts",
    "carrier_label",
    "delivery_method_label",
    "group_logistics_rows",
]