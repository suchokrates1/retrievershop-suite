"""Administracyjne akcje raportow cenowych uzywane przez blueprint."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..db import get_session
from ..models import ExcludedSeller
from ..settings_store import settings_store


@dataclass(frozen=True)
class AdminActionResult:
    message: str
    category: str


def get_max_discount_percent() -> float:
    try:
        value = settings_store.get("PRICE_MAX_DISCOUNT_PERCENT", "5")
        return float(value)
    except (ValueError, TypeError):
        return 5.0


def update_max_discount(max_discount: str) -> AdminActionResult:
    settings_store.update({"PRICE_MAX_DISCOUNT_PERCENT": max_discount})
    return AdminActionResult("Zapisano ustawienia", "success")


def list_excluded_sellers() -> list[ExcludedSeller]:
    with get_session() as session:
        return session.query(ExcludedSeller).order_by(ExcludedSeller.excluded_at.desc()).all()


def exclude_seller(seller_name_raw: str, reason_raw: str | None) -> AdminActionResult:
    seller_name = (seller_name_raw or "").strip()
    reason = (reason_raw or "").strip() or None

    if not seller_name:
        return AdminActionResult("Podaj nazwe sprzedawcy", "error")

    with get_session() as session:
        existing = session.query(ExcludedSeller).filter(
            ExcludedSeller.seller_name == seller_name
        ).first()

        if existing:
            return AdminActionResult(
                f"Sprzedawca '{seller_name}' juz jest wykluczony", "warning"
            )

        excluded = ExcludedSeller(seller_name=seller_name, reason=reason)
        session.add(excluded)
        session.commit()
        return AdminActionResult(f"Wykluczono sprzedawce '{seller_name}'", "success")


def remove_excluded_seller(seller_id: int) -> AdminActionResult:
    with get_session() as session:
        seller = session.query(ExcludedSeller).filter(ExcludedSeller.id == seller_id).first()

        if not seller:
            return AdminActionResult("Nie znaleziono sprzedawcy", "error")

        name = seller.seller_name
        session.delete(seller)
        session.commit()
        return AdminActionResult(f"Usunieto '{name}' z listy wykluczonych", "success")


def start_manual_report() -> AdminActionResult:
    from ..price_report_scheduler import start_price_report_now

    report_id = start_price_report_now()
    return AdminActionResult(f"Rozpoczeto generowanie raportu #{report_id}", "success")


def resume_report(report_id: int) -> AdminActionResult:
    from ..price_report_scheduler import resume_price_report

    resumed_id = resume_price_report(report_id)
    if resumed_id:
        return AdminActionResult(f"Wznowiono raport #{resumed_id}", "success")
    return AdminActionResult("Nie znaleziono raportu do wznowienia", "error")


def restart_report(report_id: int) -> AdminActionResult:
    from ..price_report_scheduler import restart_price_report

    result: dict[str, Any] = restart_price_report(report_id)
    if result.get("success"):
        return AdminActionResult(
            f"Zrestartowano raport #{report_id}: "
            f"{result.get('removed_errors', 0)} bledow usunieto, "
            f"{result.get('remaining', 0)} do sprawdzenia",
            "success",
        )
    return AdminActionResult(result.get("error", "Nieznany blad"), "error")


__all__ = [
    "AdminActionResult",
    "exclude_seller",
    "get_max_discount_percent",
    "list_excluded_sellers",
    "remove_excluded_seller",
    "restart_report",
    "resume_report",
    "start_manual_report",
    "update_max_discount",
]