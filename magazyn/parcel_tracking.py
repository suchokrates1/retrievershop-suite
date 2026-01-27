"""
Synchronizacja statusów przesyłek z Allegro API.

Ten moduł odpowiada za:
- Pobieranie statusów przesyłek bezpośrednio z Allegro API
- Mapowanie statusów Allegro na wewnętrzne statusy zamówień
- Aktualizację statusów w bazie danych
- Automatyczne przejścia statusów (wydrukowano → w_drodze → dostarczono)
"""

import logging
from datetime import datetime, timezone
from typing import Optional, Dict, List
from collections import defaultdict

from sqlalchemy import and_, desc, func

from .db import get_session
from .models import Order, OrderStatusLog
from .settings_store import settings_store
from . import allegro_api
from .orders import add_order_status

logger = logging.getLogger(__name__)

# Mapowanie statusów Allegro na wewnętrzne statusy
# https://developer.allegro.pl/documentation/#operation/getParcelTrackingUsingGET
# Flow: pobrano → wydrukowano → spakowano → przekazano_kurierowi → w_drodze → w_punkcie → gotowe_do_odbioru → dostarczono → zakończono
ALLEGRO_STATUS_MAP = {
    # Przesyłka utworzona/nadana
    "CREATED": "przekazano_kurierowi",  # Etykieta utworzona, paczka nadana
    
    # Przesyłka w drodze
    "COLLECTED": "w_drodze",  # Odebrana przez kuriera
    "IN_TRANSIT": "w_drodze",  # W tranzycie
    "OUT_FOR_DELIVERY": "w_drodze",  # W doręczeniu
    
    # W punkcie odbioru (paczkomat/punkt)
    "AT_PICKUP_POINT": "w_punkcie",  # Dostarczona do punktu odbioru
    
    # Gotowe do odbioru (paczkomat/punkt)
    "READY_TO_PICKUP": "gotowe_do_odbioru",  # Gotowa do odbioru w punkcie
    "PICKUP_REMINDER": "gotowe_do_odbioru",  # Przypomnienie o odbiorze
    "AVIZO": "gotowe_do_odbioru",  # Awizo pozostawione
    
    # Dostarczono
    "DELIVERED": "dostarczono",  # Doręczona do odbiorcy
    
    # Problemy
    "NOT_DELIVERED": "niedostarczono",  # Nieudane doręczenie
    "RETURNED_TO_SENDER": "zwrot",  # Zwrócona do nadawcy
    "OTHER": None,  # Inny status - nie zmieniamy
}

# Przewoźnicy - mapowanie nazw BaseLinker/Allegro na ID API
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


def get_carrier_id(delivery_method: Optional[str]) -> Optional[str]:
    """
    Mapuj nazwę metody dostawy na ID przewoźnika w Allegro API.
    
    Args:
        delivery_method: Nazwa metody dostawy z BaseLinker
        
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
                    OrderStatusLog.status.in_(["wydrukowano", "w_drodze", "w_punkcie"]),
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
                            events = waybill_data.get("events", [])
                            
                            if not waybill or waybill not in waybill_map:
                                continue
                            
                            order = waybill_map[waybill]
                            
                            # Znajdź najnowszy event
                            if events:
                                latest_event = max(events, key=lambda e: e.get("occurredAt", ""))
                                allegro_status = latest_event.get("type")
                                description = latest_event.get("description", "")
                                
                                # Mapuj na wewnętrzny status
                                new_status = ALLEGRO_STATUS_MAP.get(allegro_status)
                                
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
