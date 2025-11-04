import pytest
from magazyn.factory import create_app
from magazyn.db import get_session, reset_db
from magazyn.settings_store import settings_store

@pytest.fixture
def app(tmp_path):
    db_path = tmp_path / "test.db"
    settings_store.update({
        "DB_PATH": str(db_path),
        "COMMISSION_ALLEGRO": 10.0,
        "API_TOKEN": "test-token",
        "PAGE_ACCESS_TOKEN": "test-token",
        "RECIPIENT_ID": "test-id"
    })

    app = create_app({
        'TESTING': True,
        'WTF_CSRF_ENABLED': False,
        'SERVER_NAME': 'localhost'
    })

    with app.app_context():
        reset_db()

    yield app

    with app.app_context():
        reset_db()

@pytest.fixture
def client(app):
    with app.test_client() as client:
        yield client

@pytest.fixture
def login(client, app):
    with app.app_context():
        with client.session_transaction() as sess:
            sess["username"] = "tester"
    yield
