"""Testy tworzenia przesylek przez PrintShipmentCreator."""

from unittest.mock import Mock

import pytest

from magazyn.services.print_agent_errors import IncompleteReceiverData
from magazyn.services.print_agent_shipment_creation import PrintShipmentCreator


def _creator(**overrides):
    defaults = {
        "logger": Mock(),
        "settings_store": Mock(get=Mock(return_value="")),
        "fetch_order_detail": Mock(),
        "resolve_delivery_service_id": Mock(),
        "resolve_carrier_id": Mock(return_value="INPOST"),
        "create_shipment": Mock(),
        "wait_for_shipment_creation": Mock(),
        "get_shipment_details": Mock(),
        "add_shipment_tracking": Mock(),
        "update_fulfillment_status": Mock(),
        "save_state_value": Mock(),
    }
    defaults.update(overrides)
    return PrintShipmentCreator(**defaults)


def _ready_order(order_id="allegro_order-1"):
    return {
        "order_id": order_id,
        "delivery_method": "Allegro Paczkomaty InPost",
        "delivery_fullname": "",
        "phone": "",
        "delivery_point_id": "KRA01A",
        "products": [{"name": "Obroza", "quantity": 1}],
    }


def test_sync_tracking_skips_manual_add_for_allegro_carrier():
    add_tracking = Mock()
    update_fulfillment = Mock()
    creator = _creator(
        add_shipment_tracking=add_tracking,
        update_fulfillment_status=update_fulfillment,
    )

    creator._sync_tracking_and_fulfillment(
        "checkout-uuid",
        "allegro_order-1",
        "ALLEGRO",
        "A004QM65J2",
    )

    add_tracking.assert_not_called()
    update_fulfillment.assert_called_once_with("checkout-uuid", "PROCESSING")


def test_sync_tracking_adds_for_inpost_carrier():
    add_tracking = Mock()
    update_fulfillment = Mock()
    creator = _creator(
        add_shipment_tracking=add_tracking,
        update_fulfillment_status=update_fulfillment,
    )

    creator._sync_tracking_and_fulfillment(
        "checkout-uuid",
        "allegro_order-2",
        "INPOST",
        "620999684080180672519497",
    )

    add_tracking.assert_called_once_with(
        "checkout-uuid",
        carrier_id="INPOST",
        waybill="620999684080180672519497",
    )
    update_fulfillment.assert_called_once_with("checkout-uuid", "PROCESSING")


def test_create_hydrates_receiver_and_calls_shipment_api():
    order_data = _ready_order()
    fetch_detail = Mock(
        return_value={
            "delivery": {
                "method": {
                    "id": "delivery-method-1",
                    "name": "Allegro Paczkomaty InPost",
                },
                "address": {
                    "firstName": "DARIUSZ",
                    "lastName": "ODZIEMCZYK",
                    "phoneNumber": "+48111222333",
                },
                "pickupPoint": {"id": "KRA01A"},
            }
        }
    )
    create_shipment = Mock(return_value={"commandId": "cmd-1"})
    wait_creation = Mock(return_value={"shipmentId": "ship-1"})
    get_details = Mock(return_value={"packages": [{"waybill": "WAYBILL1"}]})
    creator = _creator(
        fetch_order_detail=fetch_detail,
        create_shipment=create_shipment,
        wait_for_shipment_creation=wait_creation,
        get_shipment_details=get_details,
    )

    result = creator.create("allegro_order-1", "checkout-1", order_data)

    assert order_data["delivery_fullname"] == "DARIUSZ ODZIEMCZYK"
    assert order_data["phone"] == "+48111222333"
    create_shipment.assert_called_once()
    receiver = create_shipment.call_args.kwargs["receiver"]
    assert receiver["name"] == "DARIUSZ ODZIEMCZYK"
    assert receiver["phone"] == "+48111222333"
    assert result[0]["shipment_id"] == "ship-1"


def test_create_raises_incomplete_receiver_when_still_missing_after_hydrate():
    order_data = _ready_order()
    fetch_detail = Mock(
        return_value={
            "delivery": {
                "method": {
                    "id": "delivery-method-1",
                    "name": "Allegro Paczkomaty InPost",
                },
                "address": {},
                "pickupPoint": {"id": "KRA01A"},
            }
        }
    )
    create_shipment = Mock()
    creator = _creator(
        fetch_order_detail=fetch_detail,
        create_shipment=create_shipment,
    )

    with pytest.raises(IncompleteReceiverData):
        creator.create("allegro_order-1", "checkout-1", order_data)

    create_shipment.assert_not_called()


def test_create_maps_receiver_validation_error_to_incomplete():
    order_data = _ready_order()
    order_data["delivery_fullname"] = "Jan Kowalski"
    order_data["phone"] = "500600700"
    fetch_detail = Mock(
        return_value={
            "delivery": {
                "method": {"id": "delivery-method-1", "name": "InPost"},
                "address": {
                    "firstName": "Jan",
                    "lastName": "Kowalski",
                    "phoneNumber": "500600700",
                },
                "pickupPoint": {"id": "KRA01A"},
            }
        }
    )
    response = Mock()
    response.json.return_value = {
        "errors": [
            {
                "path": "input.receiver.phone",
                "code": "VALIDATION_ERROR",
                "message": "empty",
            }
        ]
    }
    api_error = Exception("400 Bad Request")
    api_error.response = response
    create_shipment = Mock(side_effect=api_error)
    creator = _creator(
        fetch_order_detail=fetch_detail,
        create_shipment=create_shipment,
    )

    with pytest.raises(IncompleteReceiverData):
        creator.create("allegro_order-1", "checkout-1", order_data)
