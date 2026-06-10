"""Testy tworzenia przesylek przez PrintShipmentCreator."""

from unittest.mock import Mock

from magazyn.services.print_agent_shipment_creation import PrintShipmentCreator


def _creator(**overrides):
    defaults = {
        "logger": Mock(),
        "settings_store": Mock(),
        "fetch_order_detail": Mock(),
        "resolve_delivery_service_id": Mock(),
        "resolve_carrier_id": Mock(),
        "create_shipment": Mock(),
        "wait_for_shipment_creation": Mock(),
        "get_shipment_details": Mock(),
        "add_shipment_tracking": Mock(),
        "update_fulfillment_status": Mock(),
        "save_state_value": Mock(),
    }
    defaults.update(overrides)
    return PrintShipmentCreator(**defaults)


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
