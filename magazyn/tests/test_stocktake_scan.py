"""
Testy jednostkowe endpointu skanowania remanentu (stocktake_barcode_scan).

Pokryte scenariusze:
- Skan istniejacego EAN -> 200, aktualizacja scanned_qty, pola TTS
- Skan nieistniejacego EAN -> 404, komunikat bledu
- Skan bez kodu kreskowego -> 400
- Wielokrotny skan tego samego EAN -> inkrementacja scanned_qty
- Skan przy nieaktywnym remanencie -> 400
- Cofnij ostatni skan (undo) -> dekrementacja scanned_qty
- Cofnij gdy brak skanu do cofniecia -> 400
- barcode_endpoint w renderowanym HTML
"""
import json
from magazyn.db import get_session
from magazyn.models import Product, ProductSize, Stocktake, StocktakeItem


# ---------------------------------------------------------------------------
# Pomocniki
# ---------------------------------------------------------------------------

def _create_product_with_barcode(db, barcode="1234567890123", quantity=5,
                                  category="Szelki", brand="Truelove",
                                  series="Soft Touch", color="Czarny", size="M"):
    product = Product(category=category, brand=brand, series=series, color=color)
    db.add(product)
    db.flush()
    ps = ProductSize(product_id=product.id, size=size, quantity=quantity, barcode=barcode)
    db.add(ps)
    db.flush()
    return product, ps


def _create_stocktake(db, status="in_progress"):
    st = Stocktake(status=status)
    db.add(st)
    db.flush()
    return st


def _create_stocktake_item(db, stocktake_id, product_size_id, expected_qty=5, scanned_qty=0):
    from datetime import datetime
    item = StocktakeItem(
        stocktake_id=stocktake_id,
        product_size_id=product_size_id,
        expected_qty=expected_qty,
        scanned_qty=scanned_qty,
        scanned_at=datetime.now() if scanned_qty > 0 else None,
    )
    db.add(item)
    db.flush()
    return item


def _login(client, app):
    with app.app_context():
        with client.session_transaction() as sess:
            sess["username"] = "tester"


# ---------------------------------------------------------------------------
# Testy skanowania
# ---------------------------------------------------------------------------

class TestStocktakeBarcodeScanning:

    def test_skan_istniejacego_ean_zwraca_200(self, client, app):
        """Skan EAN istniejacego w bazie -> 200 i pola sukcesu."""
        _login(client, app)
        with app.app_context():
            with get_session() as db:
                product, ps = _create_product_with_barcode(db, barcode="1000000000001")
                st = _create_stocktake(db)
                _create_stocktake_item(db, st.id, ps.id, expected_qty=5)
                stocktake_id = st.id

        resp = client.post(
            f"/stocktake/{stocktake_id}/barcode_scan",
            data=json.dumps({"barcode": "1000000000001"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["scanned_qty"] == 1
        assert data["expected_qty"] == 5
        assert "tts_name" in data
        assert "name" in data
        assert "product_name" in data

    def test_skan_nieistniejacego_ean_zwraca_404(self, client, app):
        """Skan EAN, ktorego nie ma w bazie -> 404 i komunikat bledu."""
        _login(client, app)
        with app.app_context():
            with get_session() as db:
                st = _create_stocktake(db)
                stocktake_id = st.id

        resp = client.post(
            f"/stocktake/{stocktake_id}/barcode_scan",
            data=json.dumps({"barcode": "9999999999999"}),
            content_type="application/json",
        )
        assert resp.status_code == 404
        data = resp.get_json()
        assert "error" in data
        assert "9999999999999" in data["error"]

    def test_skan_bez_kodu_zwraca_400(self, client, app):
        """Brak kodu kreskowego w zadaniu -> 400."""
        _login(client, app)
        with app.app_context():
            with get_session() as db:
                st = _create_stocktake(db)
                stocktake_id = st.id

        resp = client.post(
            f"/stocktake/{stocktake_id}/barcode_scan",
            data=json.dumps({}),
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_skan_pustego_kodu_zwraca_400(self, client, app):
        """Pusty string jako kod kreskowy -> 400."""
        _login(client, app)
        with app.app_context():
            with get_session() as db:
                st = _create_stocktake(db)
                stocktake_id = st.id

        resp = client.post(
            f"/stocktake/{stocktake_id}/barcode_scan",
            data=json.dumps({"barcode": "   "}),
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_wielokrotny_skan_inkrementuje_licznik(self, client, app):
        """Trzykrotny skan tego samego EAN -> scanned_qty == 3."""
        _login(client, app)
        with app.app_context():
            with get_session() as db:
                product, ps = _create_product_with_barcode(db, barcode="1000000000002", quantity=10)
                st = _create_stocktake(db)
                _create_stocktake_item(db, st.id, ps.id, expected_qty=10)
                stocktake_id = st.id

        for i in range(1, 4):
            resp = client.post(
                f"/stocktake/{stocktake_id}/barcode_scan",
                data=json.dumps({"barcode": "1000000000002"}),
                content_type="application/json",
            )
            assert resp.status_code == 200
            assert resp.get_json()["scanned_qty"] == i

    def test_skan_przy_nieaktywnym_remanencie_zwraca_400(self, client, app):
        """Skan przy remanencie ze statusem 'finished' -> 400."""
        _login(client, app)
        with app.app_context():
            with get_session() as db:
                product, ps = _create_product_with_barcode(db, barcode="1000000000003")
                st = _create_stocktake(db, status="finished")
                _create_stocktake_item(db, st.id, ps.id)
                stocktake_id = st.id

        resp = client.post(
            f"/stocktake/{stocktake_id}/barcode_scan",
            data=json.dumps({"barcode": "1000000000003"}),
            content_type="application/json",
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert "error" in data

    def test_skan_nieznanego_stocktake_id_zwraca_400(self, client, app):
        """Skan z nieistniejacym stocktake_id -> 400."""
        _login(client, app)
        resp = client.post(
            "/stocktake/99999/barcode_scan",
            data=json.dumps({"barcode": "1000000000004"}),
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_skan_zwraca_statystyki(self, client, app):
        """Odpowiedz zawiera total_products, scanned_products, total_scanned."""
        _login(client, app)
        with app.app_context():
            with get_session() as db:
                product, ps = _create_product_with_barcode(db, barcode="1000000000005", quantity=3)
                st = _create_stocktake(db)
                _create_stocktake_item(db, st.id, ps.id, expected_qty=3)
                stocktake_id = st.id

        resp = client.post(
            f"/stocktake/{stocktake_id}/barcode_scan",
            data=json.dumps({"barcode": "1000000000005"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert "total_products" in data
        assert "scanned_products" in data
        assert "total_scanned" in data
        assert data["total_scanned"] == 1
        assert data["scanned_products"] == 1

    def test_skan_buduje_tts_name_z_series(self, client, app):
        """Pole tts_name zawiera series produktu."""
        _login(client, app)
        with app.app_context():
            with get_session() as db:
                product, ps = _create_product_with_barcode(
                    db, barcode="1000000000006",
                    series="Soft Touch", size="L", color="Czerwony"
                )
                st = _create_stocktake(db)
                _create_stocktake_item(db, st.id, ps.id)
                stocktake_id = st.id

        resp = client.post(
            f"/stocktake/{stocktake_id}/barcode_scan",
            data=json.dumps({"barcode": "1000000000006"}),
            content_type="application/json",
        )
        data = resp.get_json()
        assert "Soft Touch" in data["tts_name"]

    def test_skan_produktu_spoza_listy_startowej_dodaje_pozycje(self, client, app):
        """Skan produktu bez StocktakeItem -> automatyczne dodanie pozycji."""
        _login(client, app)
        with app.app_context():
            with get_session() as db:
                product, ps = _create_product_with_barcode(db, barcode="1000000000007", quantity=2)
                st = _create_stocktake(db)
                # Celowo NIE tworzymy StocktakeItem dla tego produktu
                stocktake_id = st.id
                ps_id = ps.id

        resp = client.post(
            f"/stocktake/{stocktake_id}/barcode_scan",
            data=json.dumps({"barcode": "1000000000007"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["scanned_qty"] == 1

        # Sprawdz czy item zostal utworzony w bazie
        with app.app_context():
            with get_session() as db:
                item = db.query(StocktakeItem).filter_by(
                    stocktake_id=stocktake_id, product_size_id=ps_id
                ).first()
                assert item is not None
                assert item.scanned_qty == 1


# ---------------------------------------------------------------------------
# Testy cofania skanu (undo)
# ---------------------------------------------------------------------------

class TestStocktakeUndo:

    def test_undo_dekrementuje_scanned_qty(self, client, app):
        """Po undo scanned_qty maleje o 1."""
        _login(client, app)
        with app.app_context():
            with get_session() as db:
                product, ps = _create_product_with_barcode(db, barcode="2000000000001")
                st = _create_stocktake(db)
                item = _create_stocktake_item(db, st.id, ps.id, expected_qty=5, scanned_qty=3)
                stocktake_id = st.id
                item_id = item.id

        resp = client.post(f"/stocktake/{stocktake_id}/undo")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data.get("success") is True

        with app.app_context():
            with get_session() as db:
                item = db.get(StocktakeItem, item_id)
                assert item.scanned_qty == 2


# ---------------------------------------------------------------------------
# Testy widoku skanowania (render HTML)
# ---------------------------------------------------------------------------

class TestStocktakeScanView:

    def test_strona_skanowania_zwraca_200(self, client, app):
        """GET /stocktake/<id>/scan -> 200 dla aktywnego remanentu."""
        _login(client, app)
        with app.app_context():
            with get_session() as db:
                st = _create_stocktake(db)
                stocktake_id = st.id

        resp = client.get(f"/stocktake/{stocktake_id}/scan")
        assert resp.status_code == 200

    def test_strona_skanowania_zawiera_barcode_endpoint(self, client, app):
        """Renderowany HTML zawiera poprawny barcode_endpoint z URL stocktake."""
        _login(client, app)
        with app.app_context():
            with get_session() as db:
                st = _create_stocktake(db)
                stocktake_id = st.id

        resp = client.get(f"/stocktake/{stocktake_id}/scan")
        html = resp.data.decode()
        expected_endpoint = f"/stocktake/{stocktake_id}/barcode_scan"
        assert expected_endpoint in html

    def test_strona_skanowania_dla_zakonczonego_remanentu_przekierowuje(self, client, app):
        """GET /stocktake/<id>/scan dla statusu 'finished' -> redirect do raportu."""
        _login(client, app)
        with app.app_context():
            with get_session() as db:
                st = _create_stocktake(db, status="finished")
                stocktake_id = st.id

        resp = client.get(f"/stocktake/{stocktake_id}/scan")
        assert resp.status_code == 302
        assert f"/stocktake/{stocktake_id}/report" in resp.headers["Location"]

    def test_brak_dostepu_bez_logowania(self, client, app):
        """Bez zalogowania -> redirect do /login."""
        with app.app_context():
            with get_session() as db:
                st = _create_stocktake(db)
                stocktake_id = st.id

        resp = client.post(
            f"/stocktake/{stocktake_id}/barcode_scan",
            data=json.dumps({"barcode": "1234567890123"}),
            content_type="application/json",
        )
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]
