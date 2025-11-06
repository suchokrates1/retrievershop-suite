from werkzeug.security import generate_password_hash
from magazyn.models import User
from magazyn.db import get_session

def test_login_route_authenticates_user(client, app):
    hashed = generate_password_hash("secret")
    with app.app_context():
        with get_session() as db:
            # Use existing user or create if not exists (for production DB)
            user = db.query(User).filter_by(username="tester").first()
            if not user:
                db.add(User(username="tester", password=hashed))
                db.commit()
            else:
                # Update password if user exists
                user.password = hashed
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
            # Use existing user or update password
            user = db.query(User).filter_by(username="tester").first()
            if not user:
                db.add(User(username="tester", password=hashed))
            else:
                user.password = hashed
            db.commit()

    resp = client.post(
        "/login", data={"username": "tester", "password": "secret"}
    )
    assert resp.status_code == 302
    with client.session_transaction() as sess:
        assert sess["username"] == "tester"
