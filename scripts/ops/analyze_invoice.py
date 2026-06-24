#!/usr/bin/env python3
"""Analiza i import faktury TipTop PDF."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from magazyn.domain.invoice_import import _parse_pdf, import_invoice_file


def analyze(path: Path) -> None:
    with path.open("rb") as fh:
        fh.filename = path.name
        df, invoice_number, supplier, delivery_date = _parse_pdf(fh)
    total_qty = int(df["Ilość"].sum())
    total_value = float((df["Ilość"] * df["Cena"]).sum())
    print(f"Faktura: FS {invoice_number}")
    print(f"Dostawca: {supplier}")
    print(f"Data dostawy: {delivery_date}")
    print(f"Pozycji: {len(df)} | Sztuk: {total_qty} | Wartość brutto: {total_value:.2f} zł")
    print()
    for _, row in df.iterrows():
        size = row["Rozmiar"] or "UNI"
        color = row["Kolor"] or "-"
        print(
            f"{int(row['Ilość']):>2}x {size:>4} | {color:15} | {float(row['Cena']):>7.2f} | "
            f"{row['Barcode']} | {row['Nazwa']}"
        )
    missing = df[(df["Barcode"].isna()) | (df["Barcode"] == "")]
    if len(missing):
        print("\nUWAGA: brak kodów kreskowych:", len(missing))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--import", dest="do_import", action="store_true")
    args = parser.parse_args()
    analyze(args.pdf)
    if args.do_import:
        with args.pdf.open("rb") as fh:
            fh.filename = args.pdf.name
            import_invoice_file(fh)
        print("\nZaimportowano dostawę do magazynu.")


if __name__ == "__main__":
    main()
