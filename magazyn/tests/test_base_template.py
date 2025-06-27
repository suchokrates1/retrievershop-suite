from magazyn.models import User
from werkzeug.security import generate_password_hash


def test_nav_container_class(app_mod, client, login):
    hashed = generate_password_hash("secret")
    with app_mod.get_session() as db:
        db.add(User(username="tester", password=hashed))
    resp = client.get("/")
    html = resp.get_data(as_text=True)
    import re
    nav_match = re.search(r"<nav[^>]*>(.*?)</nav>", html, re.S)
    assert nav_match, "nav section missing"
    nav_html = nav_match.group(1)
    assert "container-fluid" not in nav_html
    assert "class=\"container\"" in nav_html
