from pathlib import Path
from magazyn.services import _parse_pdf


def test_parse_tiptop_invoice():
    pdf_path = Path('magazyn/samples/sample_invoice.pdf')
    with pdf_path.open('rb') as fh:
        df = _parse_pdf(fh)

    assert len(df) == 10
    first = df.iloc[0]
    assert first['Nazwa'].startswith('Szelki dla psa Truelove Front Line Premium')
    assert first['Rozmiar'] == 'XL'
    assert first['Ilość'] == 5
    assert first['Barcode'] == '6971818794853'
    assert abs(first['Cena'] - 134.33) < 0.01

    other = df[df['Nazwa'].str.contains('Pas samochodowy')].iloc[0]
    assert other['Rozmiar'] == ''
    assert other['Ilość'] == 10
    assert other['Barcode'] == '6976128181720'
    assert abs(other['Cena'] - 53.33) < 0.01
