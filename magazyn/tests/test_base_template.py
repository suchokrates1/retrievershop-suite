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
    assert 'class="container"' in nav_html


def test_nav_contains_sales_link(app_mod, client, login):
    from flask import url_for

    with app_mod.app.test_request_context():
        sales_url = url_for("sales.list_sales")
    resp = client.get("/")
    html = resp.get_data(as_text=True)
    assert f'href="{sales_url}"' in html


def test_nav_contains_sales_settings_link(app_mod, client, login):
    from flask import url_for

    with app_mod.app.test_request_context():
        settings_url = url_for("sales.sales_settings")
    resp = client.get("/")
    html = resp.get_data(as_text=True)
    assert f'href="{settings_url}"' in html


def test_nav_contains_shipping_link(app_mod, client, login):
    from flask import url_for

    with app_mod.app.test_request_context():
        shipping_url = url_for("shipping.shipping_costs")
    resp = client.get("/")
    html = resp.get_data(as_text=True)
    assert f'href="{shipping_url}"' in html
