from unittest.mock import patch


def test_proxy_config_returns_allowlists(client, login):
    response = client.get("/api/integrations/proxy/config")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["csrf_token"]
    assert "/order/" in payload["allegro"]["prefixes"]
    assert "invoices/" in payload["wfirma"]["prefixes"]


def test_allegro_proxy_rejects_path_outside_allowlist(client, login):
    response = client.post(
        "/api/integrations/proxy/allegro",
        json={"method": "GET", "path": "/auth/oauth/token"},
    )

    assert response.status_code == 400
    payload = response.get_json()
    assert payload["ok"] is False


def test_allegro_proxy_executes_request(client, login):
    with patch(
        "magazyn.integration_proxy.execute_allegro_proxy_request",
        return_value={"ok": True, "status_code": 200, "headers": {}, "data": {"count": 1}},
    ) as mock_execute:
        response = client.post(
            "/api/integrations/proxy/allegro",
            json={
                "method": "GET",
                "path": "/order/checkout-forms",
                "params": {"limit": 1},
            },
        )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["data"]["count"] == 1
    mock_execute.assert_called_once()


def test_wfirma_proxy_executes_request(client, login):
    with patch(
        "magazyn.integration_proxy.execute_wfirma_proxy_request",
        return_value={"ok": True, "status_code": 200, "headers": {}, "data": {"status": {"code": "OK"}}},
    ) as mock_execute:
        response = client.post(
            "/api/integrations/proxy/wfirma",
            json={
                "method": "POST",
                "action": "invoices/find",
                "body": {"invoices": [{"invoice": {"limit": 1}}]},
            },
        )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["data"]["status"]["code"] == "OK"
    mock_execute.assert_called_once()


def test_wfirma_proxy_rejects_disallowed_action(client, login):
    response = client.post(
        "/api/integrations/proxy/wfirma",
        json={"method": "POST", "action": "auth/login"},
    )

    assert response.status_code == 400
    payload = response.get_json()
    assert payload["ok"] is False