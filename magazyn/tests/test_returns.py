"""Testy dla systemu zwrotow."""

import pytest
from unittest.mock import MagicMock

# Importy modeli sa rozbite po modulach domenowych.


class TestCustomerReturnsPagination:
    """Zwroty Allegro sa sortowane od najstarszych - trzeba pobrac ostatnia strone."""

    def test_fetch_recent_returns_the_newest_page(self, monkeypatch):
        from magazyn.services import return_allegro

        # Allegro zwraca count=103 i ignoruje sort - offset musi wskazac ogon listy.
        newest = [{"id": f"new{i}"} for i in range(100)]
        calls = []

        def fake_get(url, headers=None, params=None, timeout=None):
            calls.append(params)
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            if params.get("limit") == 1:
                resp.json.return_value = {"count": 103, "customerReturns": [{"id": "probe"}]}
            else:
                resp.json.return_value = {"count": 103, "customerReturns": newest}
            return resp

        monkeypatch.setattr(return_allegro.requests, "get", fake_get)

        result = return_allegro._fetch_recent_customer_returns(
            {}, return_allegro.logger, limit=100
        )

        assert len(result) == 100
        assert calls == [
            {"limit": 1, "offset": 0},
            {"limit": 100, "offset": 3},
        ]

    def test_fetch_recent_returns_fewer_than_limit(self, monkeypatch):
        from magazyn.services import return_allegro

        calls = []

        def fake_get(url, headers=None, params=None, timeout=None):
            calls.append(params)
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            if params.get("limit") == 1:
                resp.json.return_value = {"count": 5, "customerReturns": [{"id": "probe"}]}
            else:
                resp.json.return_value = {
                    "count": 5,
                    "customerReturns": [{"id": f"r{i}"} for i in range(5)],
                }
            return resp

        monkeypatch.setattr(return_allegro.requests, "get", fake_get)

        result = return_allegro._fetch_recent_customer_returns(
            {}, return_allegro.logger, limit=100
        )

        assert len(result) == 5
        # Gdy count <= limit, druga strona idzie od offset=0.
        assert calls == [
            {"limit": 1, "offset": 0},
            {"limit": 100, "offset": 0},
        ]


class TestReturnStatusMapping:
    def test_dispatched_maps_to_in_transit(self):
        from magazyn.domain.returns import (
            RETURN_STATUS_IN_TRANSIT,
            map_allegro_return_status,
        )

        assert map_allegro_return_status("DISPATCHED") == RETURN_STATUS_IN_TRANSIT


class TestReturnsSystem:
    """Testy dla systemu zwrotow."""

    def test_return_status_constants(self):
        """Test stalych statusow zwrotu."""
        from magazyn.domain.returns import (
            RETURN_STATUS_PENDING,
            RETURN_STATUS_IN_TRANSIT,
            RETURN_STATUS_DELIVERED,
            RETURN_STATUS_NOT_COLLECTED,
            RETURN_STATUS_COMPLETED,
            RETURN_STATUS_CANCELLED,
        )

        assert RETURN_STATUS_PENDING == "pending"
        assert RETURN_STATUS_IN_TRANSIT == "in_transit"
        assert RETURN_STATUS_DELIVERED == "delivered"
        assert RETURN_STATUS_NOT_COLLECTED == "not_collected"
        assert RETURN_STATUS_COMPLETED == "completed"
        assert RETURN_STATUS_CANCELLED == "cancelled"

    def test_return_status_constants_complete(self):
        """Test kompletnosci stalych statusow zwrotu."""
        from magazyn.domain.returns import (
            RETURN_STATUS_PENDING,
            RETURN_STATUS_IN_TRANSIT,
            RETURN_STATUS_DELIVERED,
            RETURN_STATUS_NOT_COLLECTED,
            RETURN_STATUS_COMPLETED,
            RETURN_STATUS_CANCELLED,
        )

        # Sprawdz ze statusy sa unikalne
        statuses = [
            RETURN_STATUS_PENDING,
            RETURN_STATUS_IN_TRANSIT,
            RETURN_STATUS_DELIVERED,
            RETURN_STATUS_NOT_COLLECTED,
            RETURN_STATUS_COMPLETED,
            RETURN_STATUS_CANCELLED,
        ]
        assert len(statuses) == len(set(statuses))

    def test_carrier_mapping(self):
        """Test mapowania przewoznikow na Allegro API."""
        from magazyn.domain.returns import map_carrier_to_allegro

        assert map_carrier_to_allegro("InPost") == "INPOST"
        assert map_carrier_to_allegro("inpost paczkomat") == "INPOST"
        assert map_carrier_to_allegro("DPD") == "DPD"
        assert map_carrier_to_allegro("dhl express") == "DHL"
        assert map_carrier_to_allegro("Poczta Polska") == "POCZTA_POLSKA"
        assert map_carrier_to_allegro("nieznany") == "ALLEGRO"
        assert map_carrier_to_allegro(None) is None

    def test_send_return_notification(self):
        """Test wysylania powiadomienia o zwrocie."""
        from magazyn.models.returns import Return
        from magazyn.services.return_notifications import send_return_notification

        mock_send_messenger = MagicMock()
        mock_send_messenger.return_value = True

        # Utworz mock zwrotu
        return_record = MagicMock(spec=Return)
        return_record.id = 1
        return_record.customer_name = "Jan Kowalski"
        return_record.items_json = (
            '[{"name": "Szelki XL", "quantity": 1}, '
            '{"name": "Smycz 2m", "quantity": 2}]'
        )
        return_record.return_tracking_number = "123456789"

        result = send_return_notification(
            return_record,
            send_message=mock_send_messenger,
        )

        assert result is True
        mock_send_messenger.assert_called_once()
        call_args = mock_send_messenger.call_args[0][0]
        assert "Jan Kowalski" in call_args
        assert "Szelki XL" in call_args
        assert "Smycz 2m" in call_args
        assert "123456789" in call_args

    def test_get_order_products_summary(self):
        """Test pobierania podsumowania produktow z zamowienia."""
        from magazyn.models.orders import Order, OrderProduct
        from magazyn.services.return_notifications import get_order_products_summary

        # Mock zamowienia z produktami
        mock_order = MagicMock(spec=Order)
        mock_product1 = MagicMock(spec=OrderProduct)
        mock_product1.ean = "1234567890123"
        mock_product1.name = "Szelki dla psa XL"
        mock_product1.quantity = 1
        mock_product1.product_size_id = 42

        mock_product2 = MagicMock(spec=OrderProduct)
        mock_product2.ean = "9876543210987"
        mock_product2.name = "Smycz 2m"
        mock_product2.quantity = 2
        mock_product2.product_size_id = 55

        mock_order.products = [mock_product1, mock_product2]

        result = get_order_products_summary(mock_order)

        assert len(result) == 2
        assert result[0]["ean"] == "1234567890123"
        assert result[0]["name"] == "Szelki dla psa XL"
        assert result[0]["quantity"] == 1
        assert result[0]["product_size_id"] == 42
        assert result[1]["name"] == "Smycz 2m"
        assert result[1]["quantity"] == 2


class TestReturnModel:
    """Testy dla modelu Return."""

    def test_return_model_fields(self):
        """Test pol modelu Return."""
        from magazyn.models.returns import Return

        # Sprawdz czy model ma wymagane pola
        assert hasattr(Return, "id")
        assert hasattr(Return, "order_id")
        assert hasattr(Return, "status")
        assert hasattr(Return, "customer_name")
        assert hasattr(Return, "items_json")
        assert hasattr(Return, "return_tracking_number")
        assert hasattr(Return, "return_carrier")
        assert hasattr(Return, "allegro_return_id")
        assert hasattr(Return, "messenger_notified")
        assert hasattr(Return, "stock_restored")
        assert hasattr(Return, "notes")
        assert hasattr(Return, "created_at")
        assert hasattr(Return, "updated_at")

    def test_return_status_log_model_fields(self):
        """Test pol modelu ReturnStatusLog."""
        from magazyn.models.returns import ReturnStatusLog

        assert hasattr(ReturnStatusLog, "id")
        assert hasattr(ReturnStatusLog, "return_id")
        assert hasattr(ReturnStatusLog, "status")
        assert hasattr(ReturnStatusLog, "notes")
        assert hasattr(ReturnStatusLog, "timestamp")


class TestReturnIntegration:
    """Testy integracyjne dla zwrotow (wymagaja kontekstu aplikacji)."""

    @pytest.fixture
    def app_context(self):
        """Fixture dla kontekstu aplikacji Flask."""
        # Ten fixture wymaga poprawnej konfiguracji aplikacji
        # W prawdziwych testach nalezy uzyc factory.create_app()
        pass

    def test_sync_returns_structure(self):
        """Test struktury zwracanej przez sync_returns."""
        # Ten test wymaga mocka bazy danych
        # Tutaj sprawdzamy tylko strukture funkcji
        from magazyn.services.return_sync import sync_returns

        # Funkcja powinna byc callable
        assert callable(sync_returns)

    def test_check_allegro_customer_returns_structure(self):
        """Test struktury check_allegro_customer_returns."""
        from magazyn.services.return_allegro import check_allegro_customer_returns

        assert callable(check_allegro_customer_returns)

    def test_restore_stock_for_return_structure(self):
        """Test struktury restore_stock_for_return."""
        from magazyn.services.return_stock import restore_stock_for_return

        assert callable(restore_stock_for_return)


class TestReturnNotificationFormat:
    """Testy formatu powiadomien."""

    def test_notification_message_format(self):
        """Test formatu wiadomosci powiadomienia."""
        from magazyn.models.returns import Return
        from magazyn.services.return_notifications import (
            build_return_notification_message,
        )

        # Sprawdz format bez wysylania
        return_record = MagicMock(spec=Return)
        return_record.id = 1
        return_record.customer_name = "Test User"
        return_record.items_json = '[{"name": "Produkt", "quantity": 1}]'
        return_record.return_tracking_number = None

        message = build_return_notification_message(return_record)
        assert "[ZWROT]" in message
        assert "Test User" in message
        assert "Produkt" in message


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
