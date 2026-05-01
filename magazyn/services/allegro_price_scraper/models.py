"""Modele danych scrapera cen Allegro."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class CompetitorOffer:
    """Reprezentuje oferte konkurencji."""

    seller: str
    price: float
    price_with_delivery: float
    is_mine: bool = False
    delivery_days: Optional[int] = None
    delivery_text: str = ""
    offer_url: str = ""
    is_super_seller: bool = False
    has_smart: bool = False
    offer_id: Optional[str] = None
    condition: str = ""


@dataclass
class PriceCheckResult:
    """Wynik sprawdzenia cen dla oferty."""

    offer_id: str
    success: bool
    my_price: Optional[float] = None
    competitors: list[CompetitorOffer] | None = None
    cheapest_competitor: Optional[CompetitorOffer] = None
    my_position: int = 0
    competitors_all_count: int = 0
    our_other_offers: list[CompetitorOffer] | None = None
    error: Optional[str] = None
    checked_at: str = ""

    def __post_init__(self) -> None:
        if self.competitors is None:
            self.competitors = []
        if self.our_other_offers is None:
            self.our_other_offers = []
        if not self.checked_at:
            self.checked_at = datetime.now().isoformat()