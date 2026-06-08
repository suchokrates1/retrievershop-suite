"""Synchronizacja statusów przesyłek z Allegro API."""

import logging
from typing import Optional, Dict, List, Tuple
from collections import defaultdict

from sqlalchemy import and_, func

from .db import get_session
from .models.orders import Order, OrderStatusLog
from .services.return_core import create_return_from_order
from .settings_store import settings_store
from . import allegro_api
from .services.order_status import add_order_status
from .status_config import ALLEGRO_TRACKING_MAP

logger = logging.getLogger(__name__)

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

CARRIER_ALLEGRO = "ALLEGRO"
UNCLAIMED_ORDER_STATUS = "nieodebrano"
RETURN_TO_SENDER_STATUSES = {"RETURNED", "RETURNED_TO_SENDER"}
PICKUP_POINT_STATUSES = {"AT_PICKUP_POINT", "READY_TO_PICKUP", "PICKUP_REMINDER", "AVIZO", "AVAILABLE_FOR_PICKUP"}
UNCLAIMED_ISSUE_HINTS = (
    "refused to accept",
    "pick-up deadline",
    "pickup deadline",
    "not picked up",
    "nie odebr",
    "odmow",
    "cancel",
)


def _collect_tracking_statuses(waybill_data: Dict) -> List[Dict[str, str]]:
    statuses: List[Dict[str, str]] = []

    def _append_status(status_code: Optional[str], occurred_at: str, description: str) -> None:
        if not status_code:
            return
        statuses.append(
            {
                "code": status_code,
                "occurred_at": occurred_at or "",
                "description": description or "",
            }
        )

    def _collect(status_list: Optional[List[Dict]]) -> None:
        for status in status_list or []:
            _append_status(
                status.get("status") or status.get("type") or status.get("code"),
                status.get("occurredAt") or status.get("dateTime") or status.get("timestamp") or "",
                status.get("description") or status.get("name") or "",
            )

    for event in waybill_data.get("events") or []:
        _append_status(
            event.get("type"),
            event.get("occurredAt") or "",
            event.get("description") or "",
        )

    _collect(waybill_data.get("statuses"))

    tracking_details = waybill_data.get("trackingDetails") or {}
    _collect(tracking_details.get("statuses"))

    return sorted(statuses, key=lambda item: (bool(item["occurred_at"]), item["occurred_at"]))


def _infer_special_order_status(tracking_statuses: List[Dict[str, str]]) -> Optional[Tuple[str, str]]:
    pickup_seen = False
    unclaimed_issue_description = ""
    returned_description = ""

    for status in tracking_statuses:
        code = (status.get("code") or "").upper()
        description = status.get("description") or ""
        description_lower = description.lower()

        if code in PICKUP_POINT_STATUSES:
            pickup_seen = True

        if code == "ISSUE" and any(hint in description_lower for hint in UNCLAIMED_ISSUE_HINTS):
            unclaimed_issue_description = description

        if code in RETURN_TO_SENDER_STATUSES:
            returned_description = description

    if returned_description:
        if pickup_seen or unclaimed_issue_description:
            return UNCLAIMED_ORDER_STATUS, unclaimed_issue_description or returned_description
        return "zwrot", returned_description

    return None


def _ensure_not_collected_return(order: Order, description: str) -> None:
    note = "Nie odebrano przesylki - wrócila do nadawcy"
    if description:
        note = f"{note}. {description}"

    create_return_from_order(
        order,
        tracking_number=order.delivery_package_nr,
        return_carrier=CARRIER_ALLEGRO,
        status="not_collected",
        notes=note,
    )


def _extract_latest_tracking_status(waybill_data: Dict) -> Tuple[Optional[str], str]:
    """
    Wyznacz najnowszy status trackingu z payloadu Allegro.

    API historycznie zwracalo liste "events", a obecnie dla czesci
    przewoznikow zwraca liste "statuses". Obslugujemy oba formaty.

    Returns:
        (status_code, description)
    """
    candidates = _collect_tracking_statuses(waybill_data)
    if not candidates:
        return None, ""

    latest = candidates[-1]
    return latest["code"], latest["description"]


def get_carrier_id(delivery_method: Optional[str], waybill: Optional[str] = None) -> Optional[str]:
    """
    Mapuj nazwę metody dostawy na ID przewoźnika w Allegro API.
    
    Args:
        delivery_method: Nazwa metody dostawy z zamowienia
        
    Returns:
        ID przewoźnika lub None jeśli nie rozpoznano
    """
    if waybill and waybill.upper().startswith("AD"):
        return CARRIER_ALLEGRO

    if not delivery_method:
        return None

    from .allegro_api.carriers import resolve_carrier_id

    carrier_id = resolve_carrier_id(delivery_method)
    if carrier_id and carrier_id != "OTHER":
        return carrier_id

    method_lower = delivery_method.lower().strip()
    for key, mapped_carrier_id in CARRIER_ID_MAP.items():
        if key in method_lower:
            return mapped_carrier_id

    return CARRIER_ALLEGRO


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
                carrier_id = get_carrier_id(order.delivery_method, order.delivery_package_nr)
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

                            tracking_statuses = _collect_tracking_statuses(waybill_data)
                            allegro_status, description = _extract_latest_tracking_status(waybill_data)
                            if not allegro_status:
                                continue

                            special_status = _infer_special_order_status(tracking_statuses)
                            if special_status:
                                new_status, special_description = special_status
                                description = special_description or description
                            else:
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
                                    if new_status == UNCLAIMED_ORDER_STATUS:
                                        _ensure_not_collected_return(order, description)
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
