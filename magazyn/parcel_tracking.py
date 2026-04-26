"""
Synchronizacja statusów przesyłek z Allegro API.

Ten moduł odpowiada za:
- Pobieranie statusów przesyłek bezpośrednio z Allegro API
- Mapowanie statusów Allegro na wewnętrzne statusy zamówień
- Aktualizację statusów w bazie danych
- Automatyczne przejścia statusów (wydrukowano → wyslano → w_transporcie → dostarczono)
"""

import logging
from typing import Optional, Dict, List, Tuple
from collections import defaultdict

from sqlalchemy import and_, func

from .db import get_session
from .models import Order, OrderStatusLog
from .settings_store import settings_store
from . import allegro_api
from .services.order_status import add_order_status

logger = logging.getLogger(__name__)

from .status_config import ALLEGRO_TRACKING_MAP

# Przewoźnicy - mapowanie nazw na ID API Allegro
CARRIER_ID_MAP = {
    "inpost": "INPOST",
    "poczta polska": "POCZTA_POLSKA",
    "dpd": "DPD",
    "ups": "UPS",
    "dhl": "DHL",
    "fedex": "FEDEX",
    "gls": "GLS",
    "allegro": "ALLEGRO",
    "paczkomaty": "INPOST",
    "orlen paczka": "ORLEN_PACZKA",
}


def _extract_latest_tracking_status(waybill_data: Dict) -> Tuple[Optional[str], str]:
    """
    Wyznacz najnowszy status trackingu z payloadu Allegro.

    API historycznie zwracalo liste "events", a obecnie dla czesci
    przewoznikow zwraca liste "statuses". Obslugujemy oba formaty.

    Returns:
        (status_code, description)
    """
    candidates: List[Tuple[bool, str, str, str]] = []

    def _collect_statuses(statuses: Optional[List[Dict]]) -> None:
        for status in statuses or []:
            status_code = status.get("status") or status.get("type") or status.get("code")
            if not status_code:
                continue
            occurred_at = (
                status.get("occurredAt")
                or status.get("dateTime")
                or status.get("timestamp")
                or ""
            )
            description = status.get("description") or status.get("name") or ""
            candidates.append((bool(occurred_at), occurred_at, status_code, description))

    for event in waybill_data.get("events") or []:
        status_code = event.get("type")
        if not status_code:
            continue
        occurred_at = event.get("occurredAt") or ""
        description = event.get("description") or ""
        candidates.append((bool(occurred_at), occurred_at, status_code, description))

    _collect_statuses(waybill_data.get("statuses"))

    tracking_details = waybill_data.get("trackingDetails") or {}
    _collect_statuses(tracking_details.get("statuses"))

    if not candidates:
        return None, ""

    _, _, latest_status, latest_description = max(candidates)
    return latest_status, latest_description


def get_carrier_id(delivery_method: Optional[str]) -> Optional[str]:
    """
    Mapuj nazwę metody dostawy na ID przewoźnika w Allegro API.
    
    Args:
        delivery_method: Nazwa metody dostawy z zamowienia
        
    Returns:
        ID przewoźnika lub None jeśli nie rozpoznano
    """
    if not delivery_method:
        return None
    
    method_lower = delivery_method.lower().strip()
    
    # Sprawdź bezpośrednie dopasowanie
    for key, carrier_id in CARRIER_ID_MAP.items():
        if key in method_lower:
            return carrier_id
    
    # Domyślnie dla zamówień Allegro używamy "ALLEGRO"
    return "ALLEGRO"


def sync_parcel_statuses() -> Dict[str, int]:
    """
    Synchronizuj statusy przesyłek z Allegro API.
    
    Proces:
    1. Pobierz zamówienia ze statusem "wydrukowano" lub "w_drodze" które mają numer przesyłki
    2. Pogrupuj według przewoźnika
    3. Pobierz statusy z Allegro API (max 20 przesyłek na żądanie)
    4. Zaktualizuj statusy zamówień na podstawie odpowiedzi
    
    Returns:
        Dict ze statystykami: {
            "checked": liczba sprawdzonych przesyłek,
            "updated": liczba zaktualizowanych zamówień,
            "errors": liczba błędów
        }
    """
    stats = {
        "checked": 0,
        "updated": 0,
        "errors": 0,
        "skipped": 0,
    }
    
    try:
        # Pobierz token dostępu
        access_token = settings_store.get("ALLEGRO_ACCESS_TOKEN")
        if not access_token:
            logger.error("Brak tokena dostępu Allegro - nie można zsynchronizować przesyłek")
            return stats
        
        with get_session() as db:
            # Pobierz zamówienia do sprawdzenia
            # Szukamy zamówień gdzie OSTATNI status to: wydrukowano, w_drodze lub w_punkcie
            # (nie sprawdzamy "dostarczono" ani starszych)
            
            # Subquery: znajdź ID ostatniego wpisu statusu dla każdego zamówienia
            latest_status_subq = (
                db.query(
                    OrderStatusLog.order_id,
                    func.max(OrderStatusLog.timestamp).label("max_timestamp")
                )
                .group_by(OrderStatusLog.order_id)
                .subquery()
            )
            
            # Główne zapytanie: zamówienia z ostatnim statusem w określonych statusach
            orders = (
                db.query(Order)
                .join(OrderStatusLog, OrderStatusLog.order_id == Order.order_id)
                .join(
                    latest_status_subq,
                    and_(
                        OrderStatusLog.order_id == latest_status_subq.c.order_id,
                        OrderStatusLog.timestamp == latest_status_subq.c.max_timestamp,
                    ),
                )
                .filter(
                    OrderStatusLog.status.in_(["wydrukowano", "spakowano", "wyslano", "w_transporcie", "w_punkcie"]),
                    Order.delivery_package_nr.isnot(None),
                    Order.delivery_package_nr != "",
                )
                .distinct()
                .all()
            )

            
            logger.info(f"Znaleziono {len(orders)} zamówień do sprawdzenia statusów")
            
            # Grupuj według przewoźnika
            by_carrier: Dict[str, List[Order]] = defaultdict(list)
            for order in orders:
                carrier_id = get_carrier_id(order.delivery_method)
                if carrier_id:
                    by_carrier[carrier_id].append(order)
                else:
                    logger.debug(f"Nie rozpoznano przewoźnika dla zamówienia {order.order_id}: {order.delivery_method}")
                    stats["skipped"] += 1
            
            # Przetwarzaj każdego przewoźnika
            for carrier_id, carrier_orders in by_carrier.items():
                logger.info(f"Sprawdzam {len(carrier_orders)} przesyłek u przewoźnika {carrier_id}")
                
                # API pozwala max 20 waybills na raz - podziel na partie
                batch_size = 20
                for i in range(0, len(carrier_orders), batch_size):
                    batch = carrier_orders[i:i+batch_size]
                    waybills = [order.delivery_package_nr for order in batch]
                    
                    try:
                        # Pobierz statusy z API
                        tracking_data = allegro_api.fetch_parcel_tracking(
                            access_token, 
                            carrier_id, 
                            waybills
                        )
                        
                        stats["checked"] += len(waybills)
                        
                        # Przetwórz odpowiedź
                        waybill_map = {order.delivery_package_nr: order for order in batch}
                        
                        for waybill_data in tracking_data.get("waybills", []):
                            waybill = waybill_data.get("waybill")
                            
                            if not waybill or waybill not in waybill_map:
                                continue
                            
                            order = waybill_map[waybill]

                            allegro_status, description = _extract_latest_tracking_status(waybill_data)
                            if not allegro_status:
                                continue

                            # Mapuj na wewnętrzny status
                            new_status = ALLEGRO_TRACKING_MAP.get(allegro_status)

                            if new_status:
                                # Pobierz obecny status zamówienia
                                current_log = db.query(OrderStatusLog).filter(
                                    OrderStatusLog.order_id == order.order_id
                                ).order_by(OrderStatusLog.timestamp.desc()).first()

                                current_status = current_log.status if current_log else None

                                # Aktualizuj tylko jeśli status się zmienił
                                if current_status != new_status:
                                    logger.info(
                                        f"Aktualizacja statusu zamówienia {order.order_id}: "
                                        f"{current_status} → {new_status} (Allegro: {allegro_status})"
                                    )

                                    # Dodaj nowy status
                                    note_text = f"Allegro tracking: {description}" if description else f"Status z API: {allegro_status}"
                                    add_order_status(
                                        db,
                                        order.order_id,
                                        new_status,
                                        notes=note_text
                                    )
                                    stats["updated"] += 1
                                else:
                                    logger.debug(
                                        f"Status zamówienia {order.order_id} bez zmian: {current_status}"
                                    )
                    
                    except Exception as e:
                        logger.error(f"Błąd podczas sprawdzania przesyłek {carrier_id}: {e}", exc_info=True)
                        stats["errors"] += len(batch)
        
        logger.info(
            f"Synchronizacja przesyłek zakończona: "
            f"sprawdzono={stats['checked']}, zaktualizowano={stats['updated']}, "
            f"błędy={stats['errors']}, pominięto={stats['skipped']}"
        )
        
    except Exception as e:
        logger.error(f"Krytyczny błąd podczas synchronizacji przesyłek: {e}", exc_info=True)
        stats["errors"] += 1
    
    return stats


def get_tracking_history(order_id: str) -> Optional[Dict]:
    """
    Pobierz szczegółową historię śledzenia dla konkretnego zamówienia.
    
    Args:
        order_id: ID zamówienia
        
    Returns:
        Słownik z historią śledzenia lub None jeśli brak danych
    """
    try:
        access_token = settings_store.get("ALLEGRO_ACCESS_TOKEN")
        if not access_token:
            logger.error("Brak tokena dostępu Allegro")
            return None
        
        with get_session() as db:
            order = db.query(Order).filter(Order.order_id == order_id).first()
            
            if not order or not order.delivery_package_nr:
                logger.warning(f"Brak numeru przesyłki dla zamówienia {order_id}")
                return None
            
            carrier_id = get_carrier_id(order.delivery_method)
            if not carrier_id:
                logger.warning(f"Nie rozpoznano przewoźnika: {order.delivery_method}")
                return None
            
            tracking_data = allegro_api.fetch_parcel_tracking(
                access_token,
                carrier_id,
                [order.delivery_package_nr]
            )
            
            if tracking_data.get("waybills"):
                return tracking_data["waybills"][0]
            
            return None
    
    except Exception as e:
        logger.error(f"Błąd podczas pobierania historii śledzenia dla {order_id}: {e}", exc_info=True)
        return None


if __name__ == "__main__":
    # Test synchronizacji
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    print("Synchronizacja statusów przesyłek...")
    stats = sync_parcel_statuses()
    print(f"Wyniki: {stats}")
