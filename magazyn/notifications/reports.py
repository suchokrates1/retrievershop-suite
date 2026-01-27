"""
Modul do generowania i wysylania raportow.

Zawiera logike formatowania raportow okresowych,
dziennych, tygodniowych i miesiecznych.
"""

import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
from decimal import Decimal

from .messenger import send_messenger, send_messenger_lines, MessengerClient


logger = logging.getLogger(__name__)


class ReportGenerator:
    """
    Generator raportow finansowych.
    
    Uzycie:
        from magazyn.domain.financial import FinancialCalculator
        
        calculator = FinancialCalculator(db, settings)
        summary = calculator.get_period_summary(start, end)
        
        generator = ReportGenerator()
        lines = generator.format_monthly_report(summary, "Styczen 2026")
        generator.send_report("Raport miesieczny", lines)
    """
    
    def __init__(self, messenger_client: Optional[MessengerClient] = None):
        """
        Args:
            messenger_client: Opcjonalny klient Messenger (uzyje domyslnego jesli brak)
        """
        self.messenger = messenger_client
    
    def format_monthly_report(
        self, 
        summary: Dict[str, Any], 
        month_name: str
    ) -> List[str]:
        """
        Formatuje raport miesieczny.
        
        Args:
            summary: Slownik z PeriodSummary.to_dict()
            month_name: Nazwa miesiaca (np. "Styczen 2026")
            
        Returns:
            Lista linii raportu
        """
        lines = [
            f"Raport za {month_name}:",
            f"Sprzedane produkty: {summary['products_sold']}",
            f"Przychod: {summary['total_revenue']:.2f} zl",
            f"Zysk brutto: {summary['gross_profit']:.2f} zl",
        ]
        
        # Koszty stale
        if summary.get('fixed_costs_list'):
            lines.append("Koszty stale:")
            for fc in summary['fixed_costs_list']:
                lines.append(f"  - {fc['name']}: {fc['amount']:.2f} zl")
            lines.append(f"Suma kosztow stalych: {summary['fixed_costs']:.2f} zl")
        
        lines.append(f"Zysk netto: {summary['net_profit']:.2f} zl")
        
        return lines
    
    def format_weekly_report(
        self, 
        summary: Dict[str, Any],
        week_number: int
    ) -> List[str]:
        """
        Formatuje raport tygodniowy.
        
        Args:
            summary: Slownik z PeriodSummary.to_dict()
            week_number: Numer tygodnia
            
        Returns:
            Lista linii raportu
        """
        return [
            f"Raport tygodniowy (tydzien {week_number}):",
            f"Zamowienia: {summary['orders_count']}",
            f"Produkty: {summary['products_sold']}",
            f"Przychod: {summary['total_revenue']:.2f} zl",
            f"Zysk: {summary['gross_profit']:.2f} zl",
        ]
    
    def format_daily_report(
        self, 
        summary: Dict[str, Any],
        date_str: str
    ) -> List[str]:
        """
        Formatuje raport dzienny.
        
        Args:
            summary: Slownik z PeriodSummary.to_dict()
            date_str: Data w formacie tekstowym
            
        Returns:
            Lista linii raportu
        """
        return [
            f"Raport dzienny ({date_str}):",
            f"Zamowienia: {summary['orders_count']}",
            f"Produkty: {summary['products_sold']}",
            f"Przychod: {summary['total_revenue']:.2f} zl",
        ]
    
    def format_profit_breakdown(
        self, 
        breakdown: Dict[str, Any]
    ) -> List[str]:
        """
        Formatuje rozklad zysku z zamowienia.
        
        Args:
            breakdown: Slownik z ProfitBreakdown.to_dict()
            
        Returns:
            Lista linii
        """
        source_info = "(API)" if breakdown['fee_source'] == 'api' else "(szac.)"
        return [
            f"Zamowienie: {breakdown['order_id']}",
            f"  Sprzedaz: {breakdown['sale_price']:.2f} zl",
            f"  Oplaty Allegro {source_info}: -{breakdown['allegro_fees']:.2f} zl",
            f"  Koszt zakupu: -{breakdown['purchase_cost']:.2f} zl",
            f"  Pakowanie: -{breakdown['packaging_cost']:.2f} zl",
            f"  Zysk: {breakdown['profit']:.2f} zl",
        ]
    
    def send_report(self, title: str, lines: List[str]) -> bool:
        """
        Wysyla raport przez Messenger.
        
        Args:
            title: Tytul raportu
            lines: Lista linii tresci
            
        Returns:
            True jesli wyslano pomyslnie
        """
        if self.messenger:
            return self.messenger.send_with_title(title, lines)
        
        # Uzyj domyslnego klienta
        full_message = "\n".join([title, ""] + lines)
        return send_messenger(full_message)


# Funkcje pomocnicze dla kompatybilnosci wstecznej

def format_period_report(
    summary: Dict[str, Any], 
    period_name: str,
    report_type: str = "monthly"
) -> List[str]:
    """
    Formatuje raport za okres.
    
    Args:
        summary: Slownik z podsumowaniem
        period_name: Nazwa okresu
        report_type: Typ raportu ('monthly', 'weekly', 'daily')
        
    Returns:
        Lista linii raportu
    """
    generator = ReportGenerator()
    
    if report_type == "weekly":
        # Probuj wyciagnac numer tygodnia z nazwy
        try:
            week_num = int(period_name.split()[-1])
        except (ValueError, IndexError):
            week_num = 0
        return generator.format_weekly_report(summary, week_num)
    elif report_type == "daily":
        return generator.format_daily_report(summary, period_name)
    else:
        return generator.format_monthly_report(summary, period_name)


def send_report(title: str, lines: List[str]) -> bool:
    """
    Wysyla raport przez Messenger.
    
    Dla kompatybilnosci wstecznej z istniejacym kodem.
    
    Args:
        title: Tytul raportu
        lines: Lista linii tresci
        
        Returns:
        True jesli wyslano pomyslnie
    """
    generator = ReportGenerator()
    return generator.send_report(title, lines)
