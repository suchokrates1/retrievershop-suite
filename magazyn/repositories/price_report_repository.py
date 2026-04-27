"""Repozytorium zapytan dla raportow cenowych."""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..models.allegro import AllegroOffer
from ..models.price_reports import PriceReport, PriceReportItem


class PriceReportRepository:
    """Centralizuje zapytania widokow i mutacji raportow cenowych."""

    def __init__(self, db: Session):
        self.db = db

    def list_reports(self) -> list[PriceReport]:
        return self.db.query(PriceReport).order_by(PriceReport.created_at.desc()).all()

    def get_report(self, report_id: int) -> PriceReport | None:
        return self.db.query(PriceReport).filter(PriceReport.id == report_id).first()

    def get_item(self, item_id: int) -> PriceReportItem | None:
        return self.db.query(PriceReportItem).filter(PriceReportItem.id == item_id).first()

    def active_report(self) -> PriceReport | None:
        return (
            self.db.query(PriceReport)
            .filter(PriceReport.status.in_(["pending", "running"]))
            .order_by(PriceReport.created_at.desc())
            .first()
        )

    def report_items(self, report_id: int, filter_mode: str = "all") -> list[PriceReportItem]:
        query = self.db.query(PriceReportItem).filter(PriceReportItem.report_id == report_id)

        if filter_mode == "not_cheapest":
            query = query.filter(
                PriceReportItem.is_cheapest == False,
                PriceReportItem.competitor_price != None,
            )
        elif filter_mode == "cheapest":
            query = query.filter(PriceReportItem.is_cheapest == True)
        elif filter_mode == "inna_aukcja_ok":
            query = query.filter(
                PriceReportItem.is_cheapest == False,
                PriceReportItem.competitor_price == None,
                PriceReportItem.error == None,
            )
        elif filter_mode == "errors":
            query = query.filter(PriceReportItem.error != None)

        return query.all()

    def count_items(self, report_id: int) -> int:
        return self.db.query(PriceReportItem).filter(PriceReportItem.report_id == report_id).count()

    def count_cheapest_items(self, report_id: int) -> int:
        return (
            self.db.query(PriceReportItem)
            .filter(PriceReportItem.report_id == report_id, PriceReportItem.is_cheapest == True)
            .count()
        )

    def all_report_items(self, report_id: int) -> list[PriceReportItem]:
        return self.db.query(PriceReportItem).filter(PriceReportItem.report_id == report_id).all()

    def offers_by_ids(self, offer_ids: list[str]) -> list[AllegroOffer]:
        if not offer_ids:
            return []
        return self.db.query(AllegroOffer).filter(AllegroOffer.offer_id.in_(offer_ids)).all()

    def allegro_offer(self, offer_id: str) -> AllegroOffer | None:
        return self.db.query(AllegroOffer).filter(AllegroOffer.offer_id == offer_id).first()

    def cheaper_sibling(self, *, product_size_id: int, offer_id: str, price: float) -> AllegroOffer | None:
        return (
            self.db.query(AllegroOffer)
            .filter(
                AllegroOffer.product_size_id == product_size_id,
                AllegroOffer.publication_status == "ACTIVE",
                AllegroOffer.offer_id != offer_id,
                AllegroOffer.price < price,
            )
            .first()
        )


__all__ = ["PriceReportRepository"]