"""Operacje na kosztach stalych panelu ustawien."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from ..db import get_session
from ..models import FixedCost


@dataclass(frozen=True)
class FixedCostActionResult:
    message: str
    category: str


def list_fixed_costs() -> tuple[list[dict], float]:
    with get_session() as db_session:
        fixed_costs = db_session.query(FixedCost).order_by(FixedCost.name).all()
        fixed_costs_list = [
            {
                "id": fixed_cost.id,
                "name": fixed_cost.name,
                "amount": float(fixed_cost.amount),
                "description": fixed_cost.description,
                "is_active": fixed_cost.is_active,
            }
            for fixed_cost in fixed_costs
        ]
    total_fixed_costs = sum(
        fixed_cost["amount"] for fixed_cost in fixed_costs_list if fixed_cost["is_active"]
    )
    return fixed_costs_list, total_fixed_costs


def _parse_amount(amount_raw: str) -> Decimal | None:
    amount_str = (amount_raw or "0").strip().replace(",", ".")
    try:
        return Decimal(amount_str)
    except (InvalidOperation, ValueError):
        return None


def add_fixed_cost(name_raw: str, amount_raw: str, description_raw: str) -> FixedCostActionResult:
    name = (name_raw or "").strip()
    description = (description_raw or "").strip()

    if not name:
        return FixedCostActionResult("Nazwa kosztu jest wymagana.", "error")

    amount = _parse_amount(amount_raw)
    if amount is None:
        return FixedCostActionResult("Nieprawidlowa kwota.", "error")

    new_cost = FixedCost(
        name=name,
        amount=amount,
        description=description if description else None,
        is_active=True,
    )
    with get_session() as db_session:
        db_session.add(new_cost)
        db_session.commit()

    return FixedCostActionResult(f"Dodano koszt staly: {name} ({amount} PLN)", "success")


def toggle_fixed_cost(cost_id: int) -> FixedCostActionResult:
    with get_session() as db_session:
        cost = db_session.query(FixedCost).filter_by(id=cost_id).first()
        if not cost:
            return FixedCostActionResult("Nie znaleziono kosztu.", "error")

        cost.is_active = not cost.is_active
        db_session.commit()
        status = "aktywny" if cost.is_active else "nieaktywny"
        return FixedCostActionResult(f"Koszt '{cost.name}' jest teraz {status}.", "info")


def delete_fixed_cost(cost_id: int) -> FixedCostActionResult:
    with get_session() as db_session:
        cost = db_session.query(FixedCost).filter_by(id=cost_id).first()
        if not cost:
            return FixedCostActionResult("Nie znaleziono kosztu.", "error")

        name = cost.name
        db_session.delete(cost)
        db_session.commit()
        return FixedCostActionResult(f"Usunieto koszt staly: {name}", "success")


def edit_fixed_cost(
    cost_id: int,
    name_raw: str,
    amount_raw: str,
    description_raw: str,
) -> FixedCostActionResult:
    with get_session() as db_session:
        cost = db_session.query(FixedCost).filter_by(id=cost_id).first()
        if not cost:
            return FixedCostActionResult("Nie znaleziono kosztu.", "error")

        name = (name_raw or "").strip()
        description = (description_raw or "").strip()
        if not name:
            return FixedCostActionResult("Nazwa kosztu jest wymagana.", "error")

        amount = _parse_amount(amount_raw)
        if amount is None:
            return FixedCostActionResult("Nieprawidlowa kwota.", "error")

        cost.name = name
        cost.amount = amount
        cost.description = description if description else None
        db_session.commit()
        return FixedCostActionResult(f"Zaktualizowano koszt staly: {name}", "success")


__all__ = [
    "FixedCostActionResult",
    "add_fixed_cost",
    "delete_fixed_cost",
    "edit_fixed_cost",
    "list_fixed_costs",
    "toggle_fixed_cost",
]