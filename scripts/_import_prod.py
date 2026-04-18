"""Import dostawy z faktury FS 2026/04/000182 na produkcji."""
import logging
import sys
sys.path.insert(0, "/app")

from magazyn.domain.invoice_import import _parse_pdf, _import_invoice_df, parse_product_name_to_fields

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

INVOICE_PATH = "/tmp/faktura_20260409.pdf"
COMMIT = "--commit" in sys.argv

with open(INVOICE_PATH, "rb") as f:
    df, invoice_number, supplier = _parse_pdf(f)

print(f"\nFaktura: {invoice_number}")
print(f"Dostawca: {supplier}")
print(f"Liczba pozycji: {len(df)}")
print()

print(f"{'Lp':>3} {'Nazwa':<50} {'Kolor':<15} {'Rozm':<6} {'Ilosc':>5} {'Cena':>8} {'Barcode':<15} {'Kat':<18} {'Seria':<22}")
print("-" * 170)

for i, row in df.iterrows():
    name = row.get("Nazwa", "")
    color = row.get("Kolor", "")
    size = row.get("Rozmiar", "")
    qty = row.get("Ilość", 0)
    price = row.get("Cena", 0)
    barcode = row.get("Barcode", "")
    category, brand, series = parse_product_name_to_fields(name)
    cat_display = category or "??? BRAK"
    series_display = series or "-"
    size_display = size if size else "UNIW"
    print(f"{i+1:>3} {name[:50]:<50} {color[:15]:<15} {size_display:<6} {qty:>5} {price:>8.2f} {str(barcode)[:15]:<15} {cat_display:<18} {series_display:<22}")

print()

if not COMMIT:
    print("=== DRY RUN ===")
else:
    from magazyn.factory import create_app
    app = create_app()
    with app.app_context():
        _import_invoice_df(df, invoice_number=invoice_number, supplier=supplier)
    print(f"Zaimportowano {len(df)} pozycji z faktury {invoice_number}.")
