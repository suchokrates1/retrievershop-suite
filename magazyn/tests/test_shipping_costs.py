import pandas as pd
import warnings


def _create_file(path):
    cols = [
        "Metoda dostawy",
        "30-44",
        "45-64",
        "65-99",
        "100-149",
        "150+",
        "Max",
    ]
    df = pd.DataFrame([
        ["ignored", "", "", "", "", "", ""],
        cols,
        ["M1", 1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
        ["M2", 2.0, 3.0, 4.0, 5.0, 6.0, 7.0],
    ])
    df.to_excel(path, index=False, header=False)


def test_shipping_costs_load(app_mod, client, login, tmp_path, monkeypatch):
    from magazyn import shipping

    file_path = tmp_path / "costs.xlsx"
    _create_file(file_path)
    monkeypatch.setattr(shipping, "ALLEGRO_COSTS_FILE", file_path)
    original_load = shipping.load_costs
    original_save = shipping.save_costs
    monkeypatch.setattr(shipping, "load_costs", lambda fp=file_path: original_load(fp))
    monkeypatch.setattr(shipping, "save_costs", lambda df, fp=file_path: original_save(df, fp))
    resp = client.get("/shipping_costs")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "M1" in html
    assert "M2" in html


def test_shipping_costs_edit(app_mod, client, login, tmp_path, monkeypatch):
    from magazyn import shipping

    file_path = tmp_path / "costs.xlsx"
    _create_file(file_path)
    monkeypatch.setattr(shipping, "ALLEGRO_COSTS_FILE", file_path)
    original_load = shipping.load_costs
    original_save = shipping.save_costs
    monkeypatch.setattr(shipping, "load_costs", lambda fp=file_path: original_load(fp))
    monkeypatch.setattr(shipping, "save_costs", lambda df, fp=file_path: original_save(df, fp))

    df = shipping.load_costs(file_path)
    data = {}
    for i in range(len(df)):
        for j, col in enumerate(df.columns[1:]):
            val = str(df.iloc[i][col])
            if i == 0 and j == 0:
                val = "9.99"
            data[f"val_{i}_{j}"] = val
    with warnings.catch_warnings(record=True) as w:
        client.post("/shipping_costs", data=data)
    assert not w
    df2 = pd.read_excel(file_path, header=None)
    assert abs(float(df2.iloc[1, 1]) - 9.99) < 0.01
