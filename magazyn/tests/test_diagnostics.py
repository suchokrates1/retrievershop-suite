import types

from magazyn import print_agent


def test_healthz_returns_ok(client, monkeypatch):
    dummy = types.SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(
        "magazyn.diagnostics.subprocess.run", lambda *args, **kwargs: dummy
    )

    response = client.get("/healthz")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "ok"
    assert payload["checks"]["cups"]["status"] == "ok"
    assert payload["checks"]["database"]["status"] == "ok"


def test_metrics_endpoint(client):
    print_agent.PRINT_QUEUE_SIZE.set(3)

    try:
        response = client.get("/metrics")

        assert response.status_code == 200
        body = response.data.decode()
        assert "magazyn_print_queue_size" in body
        assert "3.0" in body
    finally:
        print_agent.PRINT_QUEUE_SIZE.set(0)
