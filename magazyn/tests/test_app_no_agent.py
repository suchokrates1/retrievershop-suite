"""Testy aplikacji bez agenta drukowania.

Weryfikuja ze app dziala poprawnie gdy agent nie jest uruchomiony.
Uzywaja standardowego conftest.app fixture zamiast importlib.reload
aby nie psuac globalnego stanu db_mod.engine dla kolejnych testow.
"""
import uuid

import pytest


@pytest.fixture
def app_no_agent(app):
    """App fixture z wylaczonym agentem (juz wylaczony przez conftest)."""
    return app


def test_app_response_without_agent(app_no_agent):
    client = app_no_agent.test_client()
    resp = client.get("/login")
    assert resp.status_code == 200


def test_discussions_page_loads_without_error(app_no_agent):
    from magazyn.models import User, Thread, Message
    from magazyn.db import get_session
    from werkzeug.security import generate_password_hash

    with app_no_agent.app_context():
        with get_session() as db:
            user = db.query(User).filter_by(username='test').first()
            if not user:
                user = User(username='test', password=generate_password_hash('test'))
                db.add(user)

            test_thread_id = str(uuid.uuid4())
            thread = Thread(id=test_thread_id, title="Test Thread", author="test", type="dyskusja")
            db.add(thread)
            message = Message(id=str(uuid.uuid4()), thread_id=thread.id, author="test", content="Test message")
            db.add(message)
            db.commit()

        client = app_no_agent.test_client()
        with client:
            client.post('/login', data={'username': 'test', 'password': 'test'})
            resp = client.get("/discussions")
            assert resp.status_code == 200
            assert b"Test Thread" in resp.data
