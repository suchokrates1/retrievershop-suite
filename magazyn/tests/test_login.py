from werkzeug.security import generate_password_hash
from magazyn.models import User
from magazyn.db import get_session

def test_login_route_authenticates_user(client, app):
    hashed = generate_password_hash("secret")
    with app.app_context():
        with get_session() as db:
            db.add(User(username="tester", password=hashed))
            db.commit()

    resp = client.post(
        "/login", data={"username": "tester", "password": "secret"}
    )
    assert resp.status_code == 302
    with client.session_transaction() as sess:
        assert sess["username"] == "tester"

def test_login_default_session_expiry(client, app):
    hashed = generate_password_hash("secret")
    with app.app_context():
        with get_session() as db:
            db.add(User(username="tester", password=hashed))
            db.commit()

    resp = client.post(
        "/login", data={"username": "tester", "password": "secret"}
    )
    assert resp.status_code == 302
    with client.session_transaction() as sess:
        assert sess["username"] == "tester"
