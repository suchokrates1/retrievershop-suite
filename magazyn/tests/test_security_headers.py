import pytest


@pytest.mark.usefixtures("login")
def test_security_headers_are_applied(client):
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["Content-Security-Policy"] == (
        "default-src 'self'; "
        "img-src 'self' https://retrievershop.pl data:; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "font-src 'self' https://cdn.jsdelivr.net data:; "
        "connect-src 'self'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "frame-ancestors 'self'"
    )
    assert (
        response.headers["Strict-Transport-Security"]
        == "max-age=31536000; includeSubDomains"
    )
    assert response.headers["X-Content-Type-Options"] == "nosniff"
