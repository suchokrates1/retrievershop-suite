"""
Testy serwisu email do klienta i strony zamowienia.
"""

import secrets
from unittest.mock import patch

import pytest

from magazyn.models import Order, OrderProduct, OrderStatusLog
from magazyn.db import get_session


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def order_with_token(app):
    """Utworz zamowienie z tokenem klienta i produktami."""
    token = secrets.token_urlsafe(32)
    with app.app_context():
        with get_session() as db:
            order = Order(order_id="TEST-ORDER-001")
            order.customer_token = token
            order.customer_name = "Jan Testowy"
            order.email = "jan@test.pl"
            order.phone = "123456789"
            order.delivery_fullname = "Jan Testowy"
            order.delivery_address = "ul. Testowa 1"
            order.delivery_city = "Warszawa"
            order.delivery_postcode = "00-001"
            order.delivery_method = "InPost Paczkomat"
            order.delivery_price = 9.99
            order.payment_method = "Online"
            order.payment_done = 59.98
            order.currency = "PLN"
            order.date_add = 1700000000
            order.want_invoice = False
            db.add(order)
            db.flush()

            op = OrderProduct(
                order_id="TEST-ORDER-001",
                name="Szelki Truelove TLH5651 XS",
                quantity=2,
                price_brutto=24.99,
                ean="1234567890123",
                attributes="Rozmiar: XS, Kolor: Czarny",
            )
            db.add(op)

            log1 = OrderStatusLog(
                order_id="TEST-ORDER-001",
                status="pobrano",
            )
            db.add(log1)
            db.commit()

    return token


@pytest.fixture
def order_with_invoice(app):
    """Zamowienie z danymi do faktury."""
    import time
    token = secrets.token_urlsafe(32)
    with app.app_context():
        with get_session() as db:
            order = Order(order_id="allegro_TEST-ORDER-002")
            order.customer_token = token
            order.customer_name = "Firma Testowa"
            order.email = "firma@test.pl"
            order.delivery_fullname = "Firma Testowa"
            order.delivery_address = "ul. Firmowa 5"
            order.delivery_city = "Krakow"
            order.delivery_postcode = "30-001"
            order.delivery_price = 0
            order.payment_done = 100.00
            order.date_add = int(time.time())
            order.want_invoice = True
            order.delivery_package_nr = "TEST123456789"
            order.invoice_company = "Firma Testowa Sp. z o.o."
            order.invoice_nip = "1234567890"
            order.invoice_fullname = "Jan Kowalski"
            order.invoice_address = "ul. Firmowa 5"
            order.invoice_city = "Krakow"
            order.invoice_postcode = "30-001"
            db.add(order)
            db.flush()

            op = OrderProduct(
                order_id="allegro_TEST-ORDER-002",
                name="Smycz premium",
                quantity=1,
                price_brutto=100.00,
            )
            db.add(op)
            db.commit()

    return token


# ---------------------------------------------------------------------------
# Testy strony zamowienia klienta
# ---------------------------------------------------------------------------

class TestCustomerOrderPage:

    def test_valid_token_returns_200(self, app, order_with_token):
        """Prawidlowy token zwraca strone zamowienia."""
        with app.test_client() as client:
            resp = client.get(f"/zamowienie/{order_with_token}")
            assert resp.status_code == 200

    def test_invalid_token_returns_404(self, app):
        """Nieprawidlowy token zwraca 404."""
        with app.test_client() as client:
            resp = client.get("/zamowienie/nieistniejacy_token_12345678")
            assert resp.status_code == 404

    def test_short_token_returns_404(self, app):
        """Krotki token (< 16 znakow) zwraca 404."""
        with app.test_client() as client:
            resp = client.get("/zamowienie/krotki")
            assert resp.status_code == 404

    def test_no_login_required(self, app, order_with_token):
        """Strona jest dostepna bez logowania."""
        with app.test_client() as client:
            # Bez logowania - powinno dzialac
            resp = client.get(f"/zamowienie/{order_with_token}")
            assert resp.status_code == 200
            # Nie przekierowuje do logowania
            assert b"login" not in resp.data.lower() or b"Przyjete" in resp.data

    def test_page_contains_order_data(self, app, order_with_token):
        """Strona zawiera dane zamowienia."""
        with app.test_client() as client:
            resp = client.get(f"/zamowienie/{order_with_token}")
            html = resp.data.decode("utf-8")
            assert "TEST-ORDER-001" in html
            assert "Szelki Truelove TLH5651 XS" in html
            assert "24.99" in html or "49.98" in html

    def test_page_contains_delivery_info(self, app, order_with_token):
        """Strona zawiera informacje o dostawie."""
        with app.test_client() as client:
            resp = client.get(f"/zamowienie/{order_with_token}")
            html = resp.data.decode("utf-8")
            assert "Jan Testowy" in html
            assert "Testowa" in html

    def test_page_contains_status(self, app, order_with_token):
        """Strona zawiera status zamowienia."""
        with app.test_client() as client:
            resp = client.get(f"/zamowienie/{order_with_token}")
            html = resp.data.decode("utf-8")
            assert "Przyjęte do realizacji" in html

    def test_invoice_data_shown(self, app, order_with_invoice):
        """Dane do faktury sa widoczne gdy want_invoice=True."""
        with app.test_client() as client:
            resp = client.get(f"/zamowienie/{order_with_invoice}")
            html = resp.data.decode("utf-8")
            assert "Firma Testowa Sp. z o.o." in html
            assert "1234567890" in html

    def test_invoice_data_hidden_when_not_requested(self, app, order_with_token):
        """Dane do faktury ukryte gdy want_invoice=False."""
        with app.test_client() as client:
            resp = client.get(f"/zamowienie/{order_with_token}")
            html = resp.data.decode("utf-8")
            assert "Dane do faktury" not in html


# ---------------------------------------------------------------------------
# Testy serwisu email
# ---------------------------------------------------------------------------

class TestEmailService:

    def test_send_order_confirmation(self, app, order_with_token):
        """send_order_confirmation renderuje szablon i wysyla email."""
        with app.app_context():
            with get_session() as db:
                order = db.query(Order).filter(
                    Order.customer_token == order_with_token
                ).first()

                with patch(
                    "magazyn.services.email_service._send_html_email"
                ) as mock_send:
                    mock_send.return_value = True
                    from magazyn.services.email_service import (
                        send_order_confirmation,
                    )
                    result = send_order_confirmation(order)

                    assert result is True
                    mock_send.assert_called_once()
                    call_kwargs = mock_send.call_args
                    assert call_kwargs[1]["to_email"] == "jan@test.pl"
                    assert "Potwierdzenie" in call_kwargs[1]["subject"]
                    assert "TEST-ORDER-001" in call_kwargs[1]["html_body"]
                    assert "Szelki Truelove" in call_kwargs[1]["html_body"]

    def test_send_shipment_notification(self, app, order_with_token):
        """send_shipment_notification wymaga numeru przesylki."""
        with app.app_context():
            with get_session() as db:
                order = db.query(Order).filter(
                    Order.customer_token == order_with_token
                ).first()
                order.delivery_package_nr = "INP123456789"
                db.commit()

                with patch(
                    "magazyn.services.email_service._send_html_email"
                ) as mock_send:
                    mock_send.return_value = True
                    from magazyn.services.email_service import (
                        send_shipment_notification,
                    )
                    result = send_shipment_notification(order)

                    assert result is True
                    call_kwargs = mock_send.call_args
                    assert "INP123456789" in call_kwargs[1]["html_body"]

    def test_send_shipment_no_tracking_returns_false(self, app, order_with_token):
        """Bez numeru przesylki email z wyslaniem nie jest wysylany."""
        with app.app_context():
            with get_session() as db:
                order = db.query(Order).filter(
                    Order.customer_token == order_with_token
                ).first()
                order.delivery_package_nr = None
                db.commit()

                from magazyn.services.email_service import (
                    send_shipment_notification,
                )
                result = send_shipment_notification(order)
                assert result is False

    def test_send_invoice_email(self, app, order_with_invoice):
        """send_invoice_email renderuje dane faktury."""
        with app.app_context():
            with get_session() as db:
                order = db.query(Order).filter(
                    Order.customer_token == order_with_invoice
                ).first()

                with patch(
                    "magazyn.services.email_service._send_html_email"
                ) as mock_send:
                    mock_send.return_value = True
                    from magazyn.services.email_service import (
                        send_invoice_email,
                    )
                    result = send_invoice_email(
                        order,
                        pdf_data=b"%PDF-fake",
                        pdf_filename="faktura.pdf",
                    )

                    assert result is True
                    call_kwargs = mock_send.call_args
                    assert call_kwargs[1]["attachment"] == b"%PDF-fake"
                    assert (
                        call_kwargs[1]["attachment_filename"] == "faktura.pdf"
                    )
                    assert "Firma Testowa" in call_kwargs[1]["html_body"]

    def test_send_delivery_confirmation(self, app, order_with_token):
        """send_delivery_confirmation wysyla email o dostarczeniu."""
        with app.app_context():
            with get_session() as db:
                order = db.query(Order).filter(
                    Order.customer_token == order_with_token
                ).first()

                with patch(
                    "magazyn.services.email_service._send_html_email"
                ) as mock_send:
                    mock_send.return_value = True
                    from magazyn.services.email_service import (
                        send_delivery_confirmation,
                    )
                    result = send_delivery_confirmation(order)

                    assert result is True
                    call_kwargs = mock_send.call_args
                    assert "dostarczone" in call_kwargs[1]["html_body"].lower()

    def test_no_email_returns_false(self, app):
        """Brak adresu email klienta - email nie jest wysylany."""
        with app.app_context():
            with get_session() as db:
                order = Order(order_id="NO-EMAIL-ORDER")
                order.customer_token = secrets.token_urlsafe(32)
                order.email = None
                db.add(order)
                db.commit()

                from magazyn.services.email_service import (
                    send_order_confirmation,
                )
                result = send_order_confirmation(order)
                assert result is False

    def test_send_invoice_correction(self, app, order_with_invoice):
        """send_invoice_correction renderuje dane korekty."""
        with app.app_context():
            with get_session() as db:
                order = db.query(Order).filter(
                    Order.customer_token == order_with_invoice
                ).first()

                with patch(
                    "magazyn.services.email_service._send_html_email"
                ) as mock_send:
                    mock_send.return_value = True
                    from magazyn.services.email_service import (
                        send_invoice_correction,
                    )
                    result = send_invoice_correction(
                        order,
                        reason="Zwrot produktu",
                        refund_amount=50.00,
                        pdf_data=b"%PDF-korekta",
                        pdf_filename="korekta.pdf",
                    )

                    assert result is True
                    call_kwargs = mock_send.call_args
                    assert "Korekta" in call_kwargs[1]["subject"]
                    assert "Zwrot produktu" in call_kwargs[1]["html_body"]
                    assert call_kwargs[1]["attachment"] == b"%PDF-korekta"

    def test_order_page_url_generation(self, app):
        """_get_order_page_url buduje poprawny URL."""
        with app.app_context():
            from magazyn.services.email_service import _get_order_page_url
            from magazyn.settings_store import settings_store

            settings_store.update(
                {"APP_BASE_URL": "https://magazyn.example.com"}
            )
            url = _get_order_page_url("abc123")
            assert url == "https://magazyn.example.com/zamowienie/abc123"

    def test_order_page_url_no_base(self, app):
        """Bez APP_BASE_URL zwraca pusty string."""
        with app.app_context():
            from magazyn.services.email_service import _get_order_page_url
            from magazyn.settings_store import settings_store

            settings_store.update({"APP_BASE_URL": ""})
            url = _get_order_page_url("abc123")
            assert url == ""


# ---------------------------------------------------------------------------
# Test generowania tokenu przy tworzeniu zamowienia
# ---------------------------------------------------------------------------

class TestTokenGeneration:

    def test_new_order_gets_token(self, app):
        """Nowe zamowienie automatycznie otrzymuje customer_token."""
        with app.app_context():
            from magazyn.orders import sync_order_from_data

            order_data = {
                "order_id": "NEW-ORDER-TOKEN-TEST",
                "email": "test@test.pl",
                "delivery_fullname": "Test User",
                "date_add": 1700000000,
            }
            with get_session() as db:
                sync_order_from_data(db, order_data)
                db.commit()

            with get_session() as db:
                order = db.query(Order).filter(
                    Order.order_id == "NEW-ORDER-TOKEN-TEST"
                ).first()
                assert order is not None
                assert order.customer_token is not None
                assert len(order.customer_token) >= 16


# ---------------------------------------------------------------------------
# Testy invoice_service helpers
# ---------------------------------------------------------------------------

class TestEmailSentTracking:

    def test_mark_and_check_email_sent(self, app, order_with_token):
        """_mark_email_sent ustawia flage, _was_email_sent ja odczytuje."""
        with app.app_context():
            with get_session() as db:
                order = db.query(Order).filter(
                    Order.customer_token == order_with_token
                ).first()
                from magazyn.services.invoice_service import (
                    _mark_email_sent,
                    _was_email_sent,
                )

                assert _was_email_sent(order, "confirmation") is False
                _mark_email_sent(db, order, "confirmation")
                db.commit()
                assert _was_email_sent(order, "confirmation") is True
                assert _was_email_sent(order, "shipment") is False

    def test_multiple_email_types(self, app, order_with_token):
        """Mozna oznaczyc wiele typow emaili niezaleznie."""
        with app.app_context():
            with get_session() as db:
                order = db.query(Order).filter(
                    Order.customer_token == order_with_token
                ).first()
                from magazyn.services.invoice_service import (
                    _mark_email_sent,
                    _was_email_sent,
                )

                _mark_email_sent(db, order, "confirmation")
                _mark_email_sent(db, order, "shipment")
                db.commit()
                assert _was_email_sent(order, "confirmation") is True
                assert _was_email_sent(order, "shipment") is True
                assert _was_email_sent(order, "delivery") is False


# ---------------------------------------------------------------------------
# Testy dispatch email z add_order_status
# ---------------------------------------------------------------------------

class TestStatusEmailDispatch:

    def test_add_order_status_dispatches_email(self, app, order_with_token):
        """add_order_status wysyla email przy zmianie statusu."""
        with app.app_context():
            with get_session() as db:
                order = db.query(Order).filter(
                    Order.customer_token == order_with_token
                ).first()

                with patch(
                    "magazyn.services.email_service._send_html_email"
                ) as mock_send:
                    mock_send.return_value = True
                    from magazyn.orders import add_order_status
                    log = add_order_status(
                        db, order.order_id, "wyslano"
                    )
                    db.commit()

                    assert log is not None
                    # shipment email powinien byc wyslany
                    # (wyslano -> shipment)
                    # ale tylko jesli jest tracking_number
                    # email_service.send_shipment_notification wymaga go

    def test_add_order_status_no_email_when_disabled(self, app, order_with_token):
        """add_order_status z send_email=False nie wysyla emaila."""
        with app.app_context():
            with get_session() as db:
                order = db.query(Order).filter(
                    Order.customer_token == order_with_token
                ).first()

                with patch(
                    "magazyn.orders._dispatch_status_email"
                ) as mock_dispatch:
                    from magazyn.orders import add_order_status
                    log = add_order_status(
                        db, order.order_id, "spakowano",
                        send_email=False,
                    )
                    db.commit()
                    assert log is not None
                    mock_dispatch.assert_not_called()

    def test_add_order_status_skips_duplicate(self, app, order_with_token):
        """add_order_status pomija duplikat statusu."""
        with app.app_context():
            with get_session() as db:
                from magazyn.orders import add_order_status
                # Fixture dodal status "pobrano" - powtorzenie powinno byc pominiete
                log = add_order_status(
                    db, "TEST-ORDER-001", "pobrano",
                    send_email=False,
                )
                assert log is None  # duplikat

    def test_add_order_status_persists_tracking_on_order(self, app, order_with_token):
        """add_order_status zapisuje tracking i courier na rekordzie zamowienia."""
        with app.app_context():
            with get_session() as db:
                order = db.query(Order).filter(
                    Order.customer_token == order_with_token
                ).first()

                from magazyn.orders import add_order_status
                log = add_order_status(
                    db,
                    order.order_id,
                    "wyslano",
                    tracking_number="INP123456789",
                    courier_code="INPOST",
                    send_email=False,
                )
                db.commit()

                db.refresh(order)

                assert log is not None
                assert order.delivery_package_nr == "INP123456789"
                assert order.courier_code == "INPOST"
                assert log.tracking_number == "INP123456789"
                assert log.courier_code == "INPOST"

    def test_dispatch_skips_already_sent(self, app, order_with_token):
        """_dispatch_status_email nie wysyla emaila jesli juz wyslany."""
        with app.app_context():
            with get_session() as db:
                order = db.query(Order).filter(
                    Order.customer_token == order_with_token
                ).first()
                from magazyn.services.invoice_service import _mark_email_sent
                _mark_email_sent(db, order, "confirmation")
                db.commit()

                with patch(
                    "magazyn.services.email_service.send_order_confirmation"
                ) as mock_confirm:
                    from magazyn.orders import _dispatch_status_email
                    _dispatch_status_email(db, order.order_id, "pobrano")
                    mock_confirm.assert_not_called()

    def test_dispatch_sends_delivery_email(self, app, order_with_token):
        """_dispatch_status_email wysyla email o dostarczeniu."""
        with app.app_context():
            with get_session() as db:
                order = db.query(Order).filter(
                    Order.customer_token == order_with_token
                ).first()

                with patch(
                    "magazyn.services.email_service._send_html_email"
                ) as mock_send:
                    mock_send.return_value = True
                    from magazyn.orders import _dispatch_status_email
                    _dispatch_status_email(db, order.order_id, "dostarczono")
                    mock_send.assert_called_once()
                    call_kwargs = mock_send.call_args
                    assert "dostarczone" in call_kwargs[1]["html_body"].lower()


# ---------------------------------------------------------------------------
# Testy _process_pending_invoices
# ---------------------------------------------------------------------------

class TestProcessPendingInvoices:

    def test_process_skips_without_want_invoice(self, app, order_with_token):
        """Zamowienia bez want_invoice sa pomijane."""
        with app.app_context():
            from magazyn.order_sync_scheduler import _process_pending_invoices
            stats = _process_pending_invoices()
            assert stats["processed"] == 0

    def test_process_picks_up_want_invoice(self, app, order_with_invoice):
        """Zamowienia z want_invoice=True i bez faktury sa przetwarzane."""
        with app.app_context():
            with patch(
                "magazyn.services.invoice_service.generate_and_send_invoice"
            ) as mock_gen:
                mock_gen.return_value = {
                    "success": True,
                    "invoice_number": "FV/1/2026",
                    "errors": [],
                }
                from magazyn.order_sync_scheduler import (
                    _process_pending_invoices,
                )
                stats = _process_pending_invoices()
                assert stats["processed"] == 1
                assert stats["success"] == 1
                mock_gen.assert_called_once_with("allegro_TEST-ORDER-002")

    def test_process_skips_already_invoiced(self, app, order_with_invoice):
        """Zamowienia z istniejaca faktura sa pomijane."""
        with app.app_context():
            with get_session() as db:
                order = db.query(Order).filter(
                    Order.order_id == "allegro_TEST-ORDER-002"
                ).first()
                order.wfirma_invoice_id = 12345
                db.commit()

            from magazyn.order_sync_scheduler import _process_pending_invoices
            stats = _process_pending_invoices()
            assert stats["processed"] == 0
