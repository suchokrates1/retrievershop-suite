"""Testy korekt dla nieodebranych przesylek (COD bez zwrotu kasy)."""

from unittest.mock import MagicMock

from magazyn.models.orders import Order, OrderStatusLog
from magazyn.models.returns import Return, ReturnStatusLog
from magazyn.services.return_corrections import (
    NOT_COLLECTED_CORRECTION_REASON,
    process_not_collected_corrections,
    promote_unclaimed_orders_to_zwrot,
)


def _seed_not_collected(app, **order_kwargs):
    order_id = order_kwargs.pop("order_id", "allegro_unclaimed_cod")
    with app.app_context():
        from magazyn.db import get_session

        with get_session() as db:
            db.add(
                Order(
                    order_id=order_id,
                    customer_name="Anna Test",
                    payment_method=order_kwargs.get("payment_method", "Pobranie"),
                    payment_method_cod=order_kwargs.get("payment_method_cod", True),
                    wfirma_invoice_id=order_kwargs.get("wfirma_invoice_id", 111),
                    wfirma_invoice_number=order_kwargs.get(
                        "wfirma_invoice_number", "FBV 1/2026"
                    ),
                    wfirma_correction_id=order_kwargs.get("wfirma_correction_id"),
                    wfirma_correction_number=order_kwargs.get("wfirma_correction_number"),
                )
            )
            ret = Return(
                order_id=order_id,
                status="not_collected",
                customer_name="Anna Test",
                items_json="[]",
            )
            db.add(ret)
            db.commit()
            return order_id, ret.id


def test_process_not_collected_corrections_issues_cod_correction_without_refund(app):
    order_id, return_id = _seed_not_collected(app)
    captured = {}

    def fake_issue(**kwargs):
        captured.update(kwargs)
        return {"success": True, "invoice_number": "KOR 1/2026", "already_exists": False}

    with app.app_context():
        stats = process_not_collected_corrections(issue_correction=fake_issue)

        from magazyn.db import get_session

        with get_session() as db:
            log = (
                db.query(ReturnStatusLog)
                .filter(ReturnStatusLog.return_id == return_id)
                .first()
            )

    assert stats == {"processed": 1, "success": 1, "skipped": 0, "errors": 0}
    assert captured["order_id"] == order_id
    assert captured["reason"] == NOT_COLLECTED_CORRECTION_REASON
    assert captured["return_id"] is None
    assert captured["include_delivery"] is True
    assert captured["include_refund_amount"] is False
    assert captured["is_unclaimed"] is True
    assert log is not None
    assert "KOR 1/2026" in (log.notes or "")
    assert "bez zwrotu kasy" in (log.notes or "")


def test_process_not_collected_corrections_skips_when_correction_exists(app):
    _seed_not_collected(
        app,
        order_id="allegro_unclaimed_has_kor",
        wfirma_correction_id=222,
        wfirma_correction_number="KOR 9/2026",
    )
    fake_issue = MagicMock()

    with app.app_context():
        stats = process_not_collected_corrections(issue_correction=fake_issue)

    assert stats["processed"] == 0
    fake_issue.assert_not_called()


def test_process_not_collected_corrections_skips_without_invoice(app):
    _seed_not_collected(
        app,
        order_id="allegro_unclaimed_no_fv",
        wfirma_invoice_id=None,
        wfirma_invoice_number=None,
    )
    fake_issue = MagicMock()

    with app.app_context():
        stats = process_not_collected_corrections(issue_correction=fake_issue)

    assert stats["processed"] == 0
    fake_issue.assert_not_called()


def test_generate_correction_invoice_skips_when_already_exists(app):
    order_id = "allegro_correction_exists"
    with app.app_context():
        from magazyn.db import get_session
        from magazyn.services.invoice_service import generate_correction_invoice

        with get_session() as db:
            db.add(
                Order(
                    order_id=order_id,
                    wfirma_invoice_id=111,
                    wfirma_invoice_number="FBV 1/2026",
                    wfirma_correction_id=222,
                    wfirma_correction_number="KOR 9/2026",
                )
            )
            db.commit()

        result = generate_correction_invoice(order_id)

    assert result["success"] is True
    assert result["already_exists"] is True
    assert result["invoice_number"] == "KOR 9/2026"


def test_process_not_collected_corrections_prepaid_keeps_refund_amount(app):
    _seed_not_collected(
        app,
        order_id="allegro_unclaimed_prepaid",
        payment_method="Przelew",
        payment_method_cod=False,
    )
    captured = {}

    def fake_issue(**kwargs):
        captured.update(kwargs)
        return {"success": True, "invoice_number": "KOR 2/2026"}

    with app.app_context():
        stats = process_not_collected_corrections(issue_correction=fake_issue)

    assert stats["success"] == 1
    assert captured["include_refund_amount"] is True
    assert captured["is_unclaimed"] is True


def test_promote_unclaimed_orders_to_zwrot(app):
    order_id, _return_id = _seed_not_collected(
        app,
        order_id="allegro_unclaimed_promote",
    )
    with app.app_context():
        from magazyn.db import get_session

        with get_session() as db:
            db.add(OrderStatusLog(order_id=order_id, status="nieodebrano"))
            db.commit()

        stats = promote_unclaimed_orders_to_zwrot()

        with get_session() as db:
            latest = (
                db.query(OrderStatusLog)
                .filter(OrderStatusLog.order_id == order_id)
                .order_by(OrderStatusLog.timestamp.desc(), OrderStatusLog.id.desc())
                .first()
            )

    assert stats["updated"] == 1
    assert latest is not None
    assert latest.status == "zwrot"

