"""Testy _sync_from_allegro_events() z order_sync_scheduler."""
from unittest.mock import patch


from magazyn.order_sync_scheduler import _sync_from_allegro_events
from magazyn.settings_store import settings_store


# --- Inicjalizacja kursora ---


def test_sync_events_init_cursor(app):
    """Przy braku kursora - inicjalizacja na najnowszym zdarzeniu."""
    with app.app_context():
        # Upewnij sie ze nie ma kursora
        settings_store.update({"ALLEGRO_LAST_EVENT_ID": None})

        with patch(
            "magazyn.services.order_events_sync.fetch_event_stats",
            return_value={"latestEvent": {"id": "evt-init-999"}},
        ):
            stats = _sync_from_allegro_events(app)

        assert stats["events_fetched"] == 0
        assert stats["errors"] == 0
        assert settings_store.get("ALLEGRO_LAST_EVENT_ID") == "evt-init-999"


def test_sync_events_init_cursor_error(app):
    """Blad przy inicjalizacji kursora."""
    with app.app_context():
        settings_store.update({"ALLEGRO_LAST_EVENT_ID": None})

        with patch(
            "magazyn.services.order_events_sync.fetch_event_stats",
            side_effect=RuntimeError("Token error"),
        ):
            stats = _sync_from_allegro_events(app)

        assert stats["errors"] == 1
        assert settings_store.get("ALLEGRO_LAST_EVENT_ID") is None


# --- Brak nowych zdarzen ---


def test_sync_events_no_new_events(app):
    """Brak nowych zdarzen - kursor sie nie zmienia."""
    with app.app_context():
        settings_store.update({"ALLEGRO_LAST_EVENT_ID": "evt-100"})

        with patch(
            "magazyn.services.order_events_sync.fetch_order_events",
            return_value={"events": []},
        ):
            stats = _sync_from_allegro_events(app)

        assert stats["events_fetched"] == 0
        assert stats["orders_synced"] == 0
        assert settings_store.get("ALLEGRO_LAST_EVENT_ID") == "evt-100"


# --- Przetwarzanie zdarzen ---


def _make_event(event_id, event_type, checkout_form_id):
    return {
        "id": event_id,
        "type": event_type,
        "occurredAt": "2026-03-24T10:00:00Z",
        "order": {"checkoutForm": {"id": checkout_form_id}},
    }


def test_sync_events_ready_for_processing(app):
    """Zdarzenie READY_FOR_PROCESSING syncuje zamowienie."""
    with app.app_context():
        settings_store.update({"ALLEGRO_LAST_EVENT_ID": "evt-100"})

        events = [_make_event("evt-101", "READY_FOR_PROCESSING", "cf-uuid-1")]

        with patch(
            "magazyn.services.order_events_sync.fetch_order_events",
            return_value={"events": events},
        ), patch(
            "magazyn.services.order_events_sync.fetch_allegro_order_detail",
            return_value={"id": "cf-uuid-1", "lineItems": [], "buyer": {}, "payment": {}, "delivery": {}},
        ) as mock_detail, patch(
            "magazyn.services.order_events_sync.parse_allegro_order_to_data",
            return_value={"order_id": "allegro_cf-uuid-1", "external_order_id": "cf-uuid-1"},
        ) as mock_parse, patch(
            "magazyn.services.order_events_sync.sync_order_from_data",
        ) as mock_sync, patch(
            "magazyn.services.order_events_sync.get_allegro_internal_status",
            return_value="pobrano",
        ) as mock_status, patch(
            "magazyn.services.order_events_sync.add_order_status",
        ) as mock_add_status:
            stats = _sync_from_allegro_events(app)

        assert stats["events_fetched"] == 1
        assert stats["orders_synced"] == 1
        mock_detail.assert_called_once_with("cf-uuid-1")
        mock_parse.assert_called_once()
        mock_status.assert_called_once()
        mock_sync.assert_called_once()
        mock_add_status.assert_called_once()
        assert settings_store.get("ALLEGRO_LAST_EVENT_ID") == "evt-101"


def test_sync_events_bought_imports_unpaid_order(app):
    """Zdarzenie BOUGHT importuje nieoplacone zamowienie."""
    with app.app_context():
        settings_store.update({"ALLEGRO_LAST_EVENT_ID": "evt-150"})

        events = [_make_event("evt-151", "BOUGHT", "cf-uuid-unpaid")]

        with patch(
            "magazyn.services.order_events_sync.fetch_order_events",
            return_value={"events": events},
        ), patch(
            "magazyn.services.order_events_sync.fetch_allegro_order_detail",
            return_value={"id": "cf-uuid-unpaid", "lineItems": [], "buyer": {}, "payment": {}, "delivery": {}},
        ), patch(
            "magazyn.services.order_events_sync.parse_allegro_order_to_data",
            return_value={"order_id": "allegro_cf-uuid-unpaid", "external_order_id": "cf-uuid-unpaid"},
        ), patch(
            "magazyn.services.order_events_sync.sync_order_from_data",
        ) as mock_sync, patch(
            "magazyn.services.order_events_sync.get_allegro_internal_status",
            return_value="nieoplacone",
        ), patch(
            "magazyn.services.order_events_sync.add_order_status",
        ) as mock_add_status:
            stats = _sync_from_allegro_events(app)

        assert stats["orders_synced"] == 1
        mock_sync.assert_called_once()
        assert mock_add_status.call_args.args[2] == "nieoplacone"


def test_sync_events_cancelled(app):
    """Zdarzenie BUYER_CANCELLED anuluje zamowienie."""
    with app.app_context():
        settings_store.update({"ALLEGRO_LAST_EVENT_ID": "evt-200"})

        events = [_make_event("evt-201", "BUYER_CANCELLED", "cf-uuid-2")]

        with patch(
            "magazyn.services.order_events_sync.fetch_order_events",
            return_value={"events": events},
        ), patch(
            "magazyn.services.order_events_sync.add_order_status",
        ) as mock_add_status:
            stats = _sync_from_allegro_events(app)

        assert stats["orders_cancelled"] == 1
        mock_add_status.assert_called_once()
        call_args = mock_add_status.call_args
        assert call_args.args[1] == "allegro_cf-uuid-2"
        assert call_args.args[2] == "anulowano"
        assert settings_store.get("ALLEGRO_LAST_EVENT_ID") == "evt-201"


def test_sync_events_dedup_same_checkout_form(app):
    """Duplikaty zdarzen dla tego samego zamowienia sa pomijane."""
    with app.app_context():
        settings_store.update({"ALLEGRO_LAST_EVENT_ID": "evt-300"})

        events = [
            _make_event("evt-301", "READY_FOR_PROCESSING", "cf-uuid-3"),
            _make_event("evt-302", "READY_FOR_PROCESSING", "cf-uuid-3"),
        ]

        with patch(
            "magazyn.services.order_events_sync.fetch_order_events",
            return_value={"events": events},
        ), patch(
            "magazyn.services.order_events_sync.fetch_allegro_order_detail",
            return_value={"id": "cf-uuid-3", "lineItems": [], "buyer": {}, "payment": {}, "delivery": {}},
        ), patch(
            "magazyn.services.order_events_sync.parse_allegro_order_to_data",
            return_value={"order_id": "allegro_cf-uuid-3", "external_order_id": "cf-uuid-3"},
        ), patch(
            "magazyn.services.order_events_sync.sync_order_from_data",
        ) as mock_sync, patch(
            "magazyn.services.order_events_sync.get_allegro_internal_status",
            return_value="pobrano",
        ), patch(
            "magazyn.services.order_events_sync.add_order_status",
        ):
            stats = _sync_from_allegro_events(app)

        assert stats["orders_synced"] == 1
        assert stats["orders_skipped"] == 1
        mock_sync.assert_called_once()


def test_sync_events_dedup_import_types_for_same_checkout_form(app):
    """Rozne eventy zakupowe tego samego checkout-form syncujemy tylko raz."""
    with app.app_context():
        settings_store.update({"ALLEGRO_LAST_EVENT_ID": "evt-350"})

        events = [
            _make_event("evt-351", "BOUGHT", "cf-uuid-35"),
            _make_event("evt-352", "FILLED_IN", "cf-uuid-35"),
            _make_event("evt-353", "READY_FOR_PROCESSING", "cf-uuid-35"),
        ]

        with patch(
            "magazyn.services.order_events_sync.fetch_order_events",
            return_value={"events": events},
        ), patch(
            "magazyn.services.order_events_sync.fetch_allegro_order_detail",
            return_value={"id": "cf-uuid-35", "lineItems": [], "buyer": {}, "payment": {}, "delivery": {}},
        ), patch(
            "magazyn.services.order_events_sync.parse_allegro_order_to_data",
            return_value={"order_id": "allegro_cf-uuid-35", "external_order_id": "cf-uuid-35"},
        ), patch(
            "magazyn.services.order_events_sync.sync_order_from_data",
        ) as mock_sync, patch(
            "magazyn.services.order_events_sync.get_allegro_internal_status",
            return_value="pobrano",
        ), patch(
            "magazyn.services.order_events_sync.add_order_status",
        ):
            stats = _sync_from_allegro_events(app)

        assert stats["orders_synced"] == 1
        assert stats["orders_skipped"] == 2
        mock_sync.assert_called_once()


def test_sync_events_mixed_types(app):
    """Mieszane typy zdarzen - importy i anulowanie."""
    with app.app_context():
        settings_store.update({"ALLEGRO_LAST_EVENT_ID": "evt-400"})

        events = [
            _make_event("evt-401", "READY_FOR_PROCESSING", "cf-uuid-4"),
            _make_event("evt-402", "BOUGHT", "cf-uuid-5"),
            _make_event("evt-403", "BUYER_CANCELLED", "cf-uuid-6"),
            _make_event("evt-404", "FILLED_IN", "cf-uuid-7"),
        ]

        with patch(
            "magazyn.services.order_events_sync.fetch_order_events",
            return_value={"events": events},
        ), patch(
            "magazyn.services.order_events_sync.fetch_allegro_order_detail",
            return_value={"id": "cf-uuid-4", "lineItems": [], "buyer": {}, "payment": {}, "delivery": {}},
        ), patch(
            "magazyn.services.order_events_sync.parse_allegro_order_to_data",
            return_value={"order_id": "allegro_cf-uuid-4", "external_order_id": "cf-uuid-4"},
        ), patch(
            "magazyn.services.order_events_sync.sync_order_from_data",
        ), patch(
            "magazyn.services.order_events_sync.get_allegro_internal_status",
            return_value="pobrano",
        ), patch(
            "magazyn.services.order_events_sync.add_order_status",
        ):
            stats = _sync_from_allegro_events(app)

        assert stats["events_fetched"] == 4
        assert stats["orders_synced"] == 3
        assert stats["orders_cancelled"] == 1
        assert stats["orders_skipped"] == 0
        assert settings_store.get("ALLEGRO_LAST_EVENT_ID") == "evt-404"
