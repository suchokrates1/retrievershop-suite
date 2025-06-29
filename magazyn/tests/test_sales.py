from magazyn.app import app


def test_sales_get(app_mod, client, login):
    resp = client.get('/sales')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'Sprzedaż' in html


def test_sales_profit_calculation(app_mod, client, login):
    resp = client.post('/sales', data={'platform': 'allegro', 'price': '100'})
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert '82.0' in html
