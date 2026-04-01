"""
Service do trackowania błędów związanych z tworzeniem przesyłek i generowaniem etykiet.

Umożliwia:
- Zarejestrowanie błędu shipmentu (label generation, invalid address, etc.)
- Pobranie statystyk błędów per metoda dostawy
- Zidentyfikowanie unresolved errors dla re-processing
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List, Tuple

from ..db import get_session
from ..models import ShipmentError, Order

logger = logging.getLogger(__name__)


def record_shipment_error(
    order_id: str,
    error_type: str,
    error_message: Optional[str] = None,
    error_code: Optional[str] = None,
    delivery_method: Optional[str] = None,
    raw_response: Optional[str] = None,
) -> ShipmentError:
    """
    Zarejestruj błąd shipmentu w bazie.
    
    Args:
        order_id: ID zamówienia
        error_type: Typ błędu (label_generation_failed, invalid_address, shipment_creation_failed, etc.)
        error_message: Wiadomość błędu z API
        error_code: Kod błędu z API
        delivery_method: Nazwa metody dostawy
        raw_response: Raw JSON response z API (dla debugowania)
    
    Returns:
        Zapisany obiekt ShipmentError
    """
    with get_session() as db:
        error_record = ShipmentError(
            order_id=order_id,
            error_type=error_type,
            error_message=error_message,
            error_code=error_code,
            delivery_method=delivery_method,
            raw_response=raw_response,
            resolved=False,
        )
        db.add(error_record)
        db.commit()
        
        logger.warning(
            f"Shipment error recorded for {order_id}: {error_type} - {error_message} "
            f"(code: {error_code}, delivery: {delivery_method})"
        )
        
        return error_record


def mark_error_resolved(error_id: int) -> bool:
    """Oznacz błąd jako rozwiązany."""
    try:
        with get_session() as db:
            error = db.query(ShipmentError).filter(ShipmentError.id == error_id).first()
            if error:
                error.resolved = True
                db.commit()
                logger.info(f"Shipment error {error_id} marked as resolved")
                return True
    except Exception as exc:
        logger.error(f"Error marking shipment error {error_id} as resolved: {exc}")
    
    return False


def get_unresolved_errors(
    order_id: Optional[str] = None,
    error_type: Optional[str] = None,
    limit: int = 100,
) -> List[ShipmentError]:
    """
    Pobierz nierozwiązane błędy shipmentów.
    
    Args:
        order_id: Filtruj po order_id (opcjonalnie)
        error_type: Filtruj po error_type (opcjonalnie)
        limit: Limit wyników
    
    Returns:
        Lista nierozwiązanych błędów
    """
    try:
        with get_session() as db:
            query = db.query(ShipmentError).filter(ShipmentError.resolved == False)
            
            if order_id:
                query = query.filter(ShipmentError.order_id == order_id)
            
            if error_type:
                query = query.filter(ShipmentError.error_type == error_type)
            
            errors = query.order_by(ShipmentError.created_at.desc()).limit(limit).all()
            
            return errors
    except Exception as exc:
        logger.error(f"Error fetching unresolved shipment errors: {exc}")
        return []


def get_shipment_error_stats(
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
) -> Dict[str, Dict[str, int]]:
    """
    Pobierz statystyki błędów shipmentów per error_type i delivery_method.
    
    Returns:
        {
            "by_error_type": {"label_generation_failed": 5, "invalid_address": 2, ...},
            "by_delivery_method": {"inpost": 4, "dhl": 3, ...},
            "unresolved_total": 7,
            "total_in_period": 15,
        }
    """
    try:
        with get_session() as db:
            query = db.query(ShipmentError)
            
            if date_from:
                query = query.filter(ShipmentError.created_at >= date_from)
            if date_to:
                query = query.filter(ShipmentError.created_at < date_to)
            
            all_errors = query.all()
            
            # Group by error_type
            by_error_type: Dict[str, int] = {}
            for error in all_errors:
                error_type = error.error_type or "unknown"
                by_error_type[error_type] = by_error_type.get(error_type, 0) + 1
            
            # Group by delivery_method
            by_delivery_method: Dict[str, int] = {}
            for error in all_errors:
                delivery = error.delivery_method or "unknown"
                by_delivery_method[delivery] = by_delivery_method.get(delivery, 0) + 1
            
            # Count unresolved
            unresolved = sum(1 for e in all_errors if not e.resolved)
            
            return {
                "by_error_type": by_error_type,
                "by_delivery_method": by_delivery_method,
                "unresolved_total": unresolved,
                "total_in_period": len(all_errors),
            }
    except Exception as exc:
        logger.error(f"Error fetching shipment error stats: {exc}")
        return {
            "by_error_type": {},
            "by_delivery_method": {},
            "unresolved_total": 0,
            "total_in_period": 0,
        }


def get_error_rate_by_delivery_method(
    period_days: int = 30,
) -> Dict[str, float]:
    """
    Pobierz error rate (błędy / wszystkie shipment attempts) dla każdej metody dostawy.
    
    Uwaga: Trudne do obliczenia ze względu na brak pełnego logu wszystkich attempts.
    Tutaj zwracamy co najmniej liczbę błędów per metoda w ostatnich N dniach.
    
    Returns:
        {"inpost": 0.05, "dhl": 0.02, ...} - procent błędów
    """
    try:
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=period_days)
        
        stats = get_shipment_error_stats(date_from=cutoff_date)
        
        # Return raw counts as approximation
        # W pełnej implementacji trzeba by mieć log wszystkich shipments, nie tylko błędów
        return stats["by_delivery_method"]
    except Exception as exc:
        logger.error(f"Error calculating error rate: {exc}")
        return {}
