from magazyn.services.label_barcode_extract import (
    extract_dhl_box_barcodes_from_label_text,
    needs_dhl_box_label_barcode_extraction,
)

DHL_LABEL_TEXT = """
Nr przesylki: 30774980700 20.06.2026
Nr Allegro: AD02MHU8Z9
(J) JD00 003 0230864 000435460935
(2L) PL02495+83545000
"""

ORLEN_LABEL_TEXT = """
Numer paczki:
2102413302 196Presort
Numer Allegro :AD02MJHDL5
"""


def test_needs_dhl_box_label_barcode_extraction():
    assert needs_dhl_box_label_barcode_extraction("Allegro Automat DHL BOX 24/7 (AD)") is True
    assert needs_dhl_box_label_barcode_extraction("Allegro Automat ORLEN Paczka") is False
    assert needs_dhl_box_label_barcode_extraction("") is False


def test_extract_dhl_label_barcodes():
    codes = extract_dhl_box_barcodes_from_label_text(DHL_LABEL_TEXT)
    assert "30774980700" in codes
    assert "JJD000030230864000435460935" in codes
    assert "2LPL02495+83545000" in codes
    assert "AD02MHU8Z9" not in codes


def test_orlen_label_text_is_not_extracted():
    codes = extract_dhl_box_barcodes_from_label_text(ORLEN_LABEL_TEXT)
    assert codes == []
