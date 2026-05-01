"""Testy regresyjne dla parsera trackingu przesylek."""

from magazyn.parcel_tracking import (
    _collect_tracking_statuses,
    _extract_latest_tracking_status,
    _infer_special_order_status,
    get_carrier_id,
)


def test_extract_latest_status_from_events():
    payload = {
        "waybill": "WB123",
        "events": [
            {
                "occurredAt": "2026-07-01T10:00:00Z",
                "type": "CREATED",
                "description": "Label created",
            },
            {
                "occurredAt": "2026-07-01T12:00:00Z",
                "type": "IN_TRANSIT",
                "description": "Picked up from sender",
            },
        ],
    }

    status, description = _extract_latest_tracking_status(payload)

    assert status == "IN_TRANSIT"
    assert description == "Picked up from sender"


def test_extract_latest_status_from_statuses():
    payload = {
        "waybill": "WB123",
        "statuses": [
            {
                "occurredAt": "2026-07-01T10:00:00Z",
                "status": "PENDING",
                "description": "Pending",
            },
            {
                "occurredAt": "2026-07-01T12:00:00Z",
                "status": "IN_TRANSIT",
                "description": "Picked up from sender",
            },
        ],
    }

    status, description = _extract_latest_tracking_status(payload)

    assert status == "IN_TRANSIT"
    assert description == "Picked up from sender"


def test_extract_latest_status_prefers_newest_timestamp_across_formats():
    payload = {
        "waybill": "WB123",
        "events": [
            {
                "occurredAt": "2026-07-01T11:00:00Z",
                "type": "COLLECTED",
                "description": "Collected",
            }
        ],
        "statuses": [
            {
                "occurredAt": "2026-07-01T12:00:00Z",
                "status": "OUT_FOR_DELIVERY",
                "description": "Courier is on the way",
            }
        ],
    }

    status, description = _extract_latest_tracking_status(payload)

    assert status == "OUT_FOR_DELIVERY"
    assert description == "Courier is on the way"


def test_extract_latest_status_from_nested_tracking_details_statuses():
    payload = {
        "waybill": "WB123",
        "trackingDetails": {
            "createdAt": "2026-03-26T20:08:22.000Z",
            "updatedAt": "2026-03-28T10:18:42.000Z",
            "statuses": [
                {
                    "code": "PENDING",
                    "description": "Prepared by sender",
                    "occurredAt": "2026-03-26T20:08:22.000Z",
                },
                {
                    "code": "IN_TRANSIT",
                    "description": "Picked up from sender",
                    "occurredAt": "2026-03-28T10:18:42.000Z",
                },
            ],
        },
    }

    status, description = _extract_latest_tracking_status(payload)

    assert status == "IN_TRANSIT"
    assert description == "Picked up from sender"


def test_get_carrier_id_prefers_allegro_for_ad_waybill():
    assert get_carrier_id("Allegro Automat DHL BOX 24/7 (AD)", "AD0299ERY3") == "ALLEGRO"


def test_infer_not_collected_from_return_to_sender_history():
    payload = {
        "trackingDetails": {
            "statuses": [
                {
                    "code": "AVAILABLE_FOR_PICKUP",
                    "description": "Parcel is awaiting pick-up",
                    "occurredAt": "2026-04-24T08:57:32.000Z",
                },
                {
                    "code": "ISSUE",
                    "description": "Recipient has refused to accept the parcel — Purchase cancellation",
                    "occurredAt": "2026-04-28T14:35:29.000Z",
                },
                {
                    "code": "RETURNED",
                    "description": "Parcel has been returned to the sender",
                    "occurredAt": "2026-04-29T12:57:29.000Z",
                },
                {
                    "code": "DELIVERED",
                    "description": "Parcel has been delivered",
                    "occurredAt": "2026-04-30T10:42:49.000Z",
                },
            ]
        }
    }

    special_status = _infer_special_order_status(_collect_tracking_statuses(payload))

    assert special_status == (
        "nieodebrano",
        "Recipient has refused to accept the parcel — Purchase cancellation",
    )
