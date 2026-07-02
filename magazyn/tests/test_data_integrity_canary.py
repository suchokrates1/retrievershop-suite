"""Testy canary wykrywajacego nagly spadek liczby rekordow w bazie.

Kontekst: incydent z 2026-07-01, gdzie ``pytest`` uruchomiony w kontenerze
produkcyjnym wyzerowal cala baze przez ``reset_db()``. Ten canary ma wykryc
podobna sytuacje w ciagu jednego cyklu synchronizacji.
"""

import json

import pytest

from magazyn.db import get_session, reset_db
from magazyn.models.users import User
from magazyn.notifications import alerts as alerts_module
from magazyn.services import data_integrity_canary as canary


@pytest.fixture(autouse=True)
def _only_watch_users(monkeypatch):
    """Ogranicz sledzone tabele do 'users', zeby testy nie zalezaly od
    schematu zamowien/produktow."""
    monkeypatch.setattr(canary, "_watched_models", lambda: {"users": User})


def _add_users(count: int) -> None:
    with get_session() as db:
        start = db.query(User).count()
        for i in range(count):
            db.add(User(username=f"user_{start + i}", password="x"))


def test_no_alert_below_min_rows(app, monkeypatch):
    alerts_sent = []
    monkeypatch.setattr(
        alerts_module,
        "send_critical_alert",
        lambda subject, body: alerts_sent.append(body),
    )

    with app.app_context():
        _add_users(3)
        stats = canary.check_data_integrity()
        assert stats["alerts"] == []

        # Usuniecie wszystkich rekordow ponizej progu MIN_ROWS_FOR_CHECK
        # nie powinno wywolac alarmu (zbyt mala proba, np. dev/testowa baza).
        with get_session() as db:
            db.query(User).delete()
        stats = canary.check_data_integrity()
        assert stats["alerts"] == []
        assert alerts_sent == []


def test_no_alert_on_growth(app, monkeypatch):
    alerts_sent = []
    monkeypatch.setattr(
        alerts_module,
        "send_critical_alert",
        lambda subject, body: alerts_sent.append(body),
    )

    with app.app_context():
        _add_users(15)
        canary.check_data_integrity()

        _add_users(5)
        stats = canary.check_data_integrity()

        assert stats["alerts"] == []
        assert alerts_sent == []


def test_alert_on_sudden_drop(app, monkeypatch):
    alerts_sent = []
    monkeypatch.setattr(
        alerts_module,
        "send_critical_alert",
        lambda subject, body: alerts_sent.append(body),
    )

    with app.app_context():
        _add_users(15)
        canary.check_data_integrity()  # zapisuje hwm=15

        with get_session() as db:
            keep_ids = [u.id for u in db.query(User).limit(2).all()]
            db.query(User).filter(~User.id.in_(keep_ids)).delete(
                synchronize_session=False
            )

        stats = canary.check_data_integrity()

        assert len(stats["alerts"]) == 1
        assert "users" in stats["alerts"][0]
        assert len(alerts_sent) == 1


def test_hwm_survives_full_db_reset(app, monkeypatch):
    """To jest test odtwarzajacy dokladnie scenariusz incydentu: baza zostaje
    calkowicie wyzerowana (reset_db), ale plik z historycznym maksimum na
    dysku PRZETRWA i canary nadal wykryje anomalie."""
    alerts_sent = []
    monkeypatch.setattr(
        alerts_module,
        "send_critical_alert",
        lambda subject, body: alerts_sent.append(body),
    )

    with app.app_context():
        _add_users(20)
        canary.check_data_integrity()

        hwm_path = canary._hwm_file_path()
        assert hwm_path.exists()
        assert json.loads(hwm_path.read_text())["users"] == 20

        # Symulacja incydentu: DROP ALL + odtworzenie pustego schematu.
        reset_db()

        assert hwm_path.exists(), "Plik HWM nie powinien zniknac po reset_db()"

        stats = canary.check_data_integrity()

        assert len(stats["alerts"]) == 1
        assert len(alerts_sent) == 1
