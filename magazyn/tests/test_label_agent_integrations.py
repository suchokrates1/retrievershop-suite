"""Testy regresyjne dla integracji runtime LabelAgent."""

from types import SimpleNamespace
from unittest.mock import Mock

from magazyn.services.label_agent_integrations import create_allegro_shipment
from magazyn.services.print_agent_runtime_shipments import get_order_packages_from_shipment_management


def test_create_allegro_shipment_uses_agent_factory():
    creator = Mock()
    creator.create.return_value = [{"shipment_id": "ship-1"}]
    shipment_creator_factory = Mock(return_value=creator)
    agent = SimpleNamespace(
        _shipment_creator=shipment_creator_factory,
        last_order_data={"order_id": "allegro_test"},
    )

    result = create_allegro_shipment(agent, "allegro_test", "checkout-1")

    assert result == [{"shipment_id": "ship-1"}]
    shipment_creator_factory.assert_called_once_with()
    creator.create.assert_called_once_with("allegro_test", "checkout-1", agent.last_order_data)


def test_get_order_packages_creates_new_shipment_without_mapping():
    load_state_value = Mock(return_value=None)
    save_state_value = Mock()
    create_allegro_shipment = Mock(return_value=[{"shipment_id": "ship-1"}])
    logger = Mock()

    result = get_order_packages_from_shipment_management(
        "allegro_checkout-123",
        load_state_value=load_state_value,
        save_state_value=save_state_value,
        get_shipment_details=Mock(),
        create_allegro_shipment=create_allegro_shipment,
        logger=logger,
    )

    assert result == [{"shipment_id": "ship-1"}]
    create_allegro_shipment.assert_called_once_with("allegro_checkout-123", "checkout-123")
    save_state_value.assert_not_called()


def test_get_order_packages_clears_broken_mapping_and_falls_back_to_creation():
    load_state_value = Mock(return_value="sm-123")
    save_state_value = Mock()
    get_shipment_details = Mock(side_effect=RuntimeError("boom"))
    create_allegro_shipment = Mock(return_value=[{"shipment_id": "ship-2"}])
    logger = Mock()

    result = get_order_packages_from_shipment_management(
        "allegro_checkout-456",
        load_state_value=load_state_value,
        save_state_value=save_state_value,
        get_shipment_details=get_shipment_details,
        create_allegro_shipment=create_allegro_shipment,
        logger=logger,
    )

    assert result == [{"shipment_id": "ship-2"}]
    save_state_value.assert_called_once_with("sm_shipment:allegro_checkout-456", None)
    create_allegro_shipment.assert_called_once_with("allegro_checkout-456", "checkout-456")