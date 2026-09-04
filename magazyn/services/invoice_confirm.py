"""Potwierdzenie importu faktury: zapis dostaw i uzupelnienie pustych EAN."""

from __future__ import annotations

import logging
import os
from typing import Any, Mapping

from flask import flash, session

from ..db import get_session, record_purchase
from ..domain.invoice_import import import_invoice_rows
from ..domain.products import _to_decimal, _to_int
from ..models.products import ProductSize

logger = logging.getLogger(__name__)


def confirm_invoice_submission(form: Mapping[str, Any]) -> None:
    """Zapisz zaakceptowane pozycje z sesji recenzji faktury."""
    rows = session.get("invoice_rows") or []
    invoice_number = session.get("invoice_number")
    supplier = session.get("invoice_supplier")
    delivery_date = session.get("invoice_delivery_date")
    confirmed = []
    for idx, base in enumerate(rows):
        if not form.get(f"accept_{idx}"):
            continue
        ps_id = form.get(f"ps_id_{idx}")
        qty_val = form.get(f"quantity_{idx}", base.get("Ilość"))
        price_val = form.get(f"price_{idx}", base.get("Cena"))
        barcode_val = form.get(f"barcode_{idx}", base.get("Barcode"))
        if ps_id:
            _record_matched_size(
                ps_id,
                qty_val,
                price_val,
                barcode_val,
                invoice_number=invoice_number,
                supplier=supplier,
                delivery_date=delivery_date,
            )
            continue
        confirmed.append(
            {
                "Nazwa": form.get(f"name_{idx}", base.get("Nazwa")),
                "Kolor": form.get(f"color_{idx}", base.get("Kolor")),
                "Rozmiar": form.get(f"size_{idx}", base.get("Rozmiar")),
                "Ilość": qty_val,
                "Cena": price_val,
                "Barcode": barcode_val,
            }
        )
    if confirmed:
        try:
            import_invoice_rows(
                confirmed,
                invoice_number=invoice_number,
                supplier=supplier,
                delivery_date=delivery_date,
            )
            flash("Zaimportowano fakture", "success")
        except Exception as exc:
            logger.exception("Blad podczas potwierdzania faktury")
            flash(f"Blad podczas importu faktury: {exc}", "error")
    _clear_invoice_session()


def _record_matched_size(
    ps_id: str,
    qty_val,
    price_val,
    barcode_val,
    *,
    invoice_number,
    supplier,
    delivery_date,
) -> None:
    with get_session() as db:
        ps = db.query(ProductSize).filter_by(id=int(ps_id)).first()
        if not ps:
            return
        record_purchase(
            ps.product_id,
            ps.size,
            _to_int(qty_val),
            _to_decimal(price_val),
            barcode=barcode_val,
            invoice_number=invoice_number,
            supplier=supplier,
            purchase_date=delivery_date,
        )


def _clear_invoice_session() -> None:
    pdf_path = session.pop("invoice_pdf", None)
    if pdf_path:
        try:
            os.remove(pdf_path)
        except OSError:
            pass
    session.pop("invoice_rows", None)
    session.pop("invoice_number", None)
    session.pop("invoice_supplier", None)
    session.pop("invoice_delivery_date", None)
