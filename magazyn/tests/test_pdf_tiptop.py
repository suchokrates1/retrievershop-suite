from pathlib import Path
import io
from magazyn import services

_parse_pdf = services._parse_pdf


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


class FakePage:
    def __init__(self, text: str):
        self._text = text

    def extract_text(self):
        return self._text


def _run_fake_pdf(texts, monkeypatch):
    """Helper to run _parse_pdf with mocked PdfReader."""

    class FakePdfReader:
        def __init__(self, *_args, **_kwargs):
            self.pages = [FakePage(t) for t in texts]

    monkeypatch.setattr(services, "PdfReader", FakePdfReader)
    return _parse_pdf(io.BytesIO(b"dummy"))


def test_parse_tiptop_invoice_extra_spaces(monkeypatch):
    lines = [
        "1Szelki Extra  ",
        "  czarny   3,000   szt.   100,00  0  100,00  23%  300,00  69,00  369,00  ",
        "   Wariant:  XL  (EX-XL)  3,000  szt.  Kod kreskowy:  1234567890123  ",
        "  3,000  ",
    ]
    df = _run_fake_pdf(["\n".join(lines)], monkeypatch)
    assert len(df) == 1
    row = df.iloc[0]
    assert row["Ilość"] == 3
    assert row["Rozmiar"] == "XL"
    assert row["Barcode"] == "1234567890123"


def test_parse_tiptop_invoice_unusual_order(monkeypatch):
    item2 = [
        "2Szelki B   ",
        " zielony  1,000  szt.  50,00   0   50,00  23%  50,00  11,50  61,50 ",
        "  Wariant: S    (B-S-GRN)  1,000  szt.  Kod kreskowy:  2222222222222  ",
        " 1,000  ",
    ]

    item1 = [
        "1Szelki A",
        " czarny  2,000  szt.  100,00  0  100,00  23%  200,00  46,00  246,00 ",
        " Wariant: M (A-M-BLK) 2,000 szt. Kod kreskowy: 1111111111111 ",
        " 2,000 ",
    ]

    df = _run_fake_pdf(["\n".join(item2), "\n".join(item1)], monkeypatch)
    assert len(df) == 2
    b_row = df[df["Barcode"] == "2222222222222"].iloc[0]
    assert b_row["Ilość"] == 1
    assert b_row["Rozmiar"] == "S"

    a_row = df[df["Barcode"] == "1111111111111"].iloc[0]
    assert a_row["Ilość"] == 2
    assert a_row["Rozmiar"] == "M"
