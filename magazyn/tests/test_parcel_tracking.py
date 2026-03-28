"""Testy regresyjne dla parsera trackingu przesylek."""

from magazyn.parcel_tracking import _extract_latest_tracking_status


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
