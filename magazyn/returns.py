"""
System oblugi zwrotow produktow.

Ten modul odpowiada za:
- Wykrywanie zamowien ze statusem Zwrot w BaseLinkerze
- Tworzenie rekordow zwrotow w bazie
- Wysylanie powiadomien Messenger o nowych zwrotach
- Sledzenie paczek zwrotnych
- Przywracanie stanow magazynowych po otrzymaniu zwrotu
"""

import json
import logging
from datetime import datetime
from typing import Optional, Dict, List, Any, Tuple

import requests
from sqlalchemy import desc

from .db import get_session
from .models import Return, ReturnStatusLog, Order, OrderProduct, ProductSize, AllegroOffer
from .config import settings
from .notifications import send_messenger
from . import allegro_api

logger = logging.getLogger(__name__)

# Status zwrotu w BaseLinker
BASELINKER_RETURN_STATUS_ID = 91623

# Statusy zwrotu
RETURN_STATUS_PENDING = "pending"        # Zgloszony zwrot
RETURN_STATUS_IN_TRANSIT = "in_transit"  # Paczka w drodze
RETURN_STATUS_DELIVERED = "delivered"    # Paczka dostarczona do nas
RETURN_STATUS_COMPLETED = "completed"    # Stan przywrocony
RETURN_STATUS_CANCELLED = "cancelled"    # Anulowany


def _add_return_status_log(db, return_id: int, status: str, notes: str = None) -> None:
    """Dodaj wpis do historii statusow zwrotu."""
    log = ReturnStatusLog(
        return_id=return_id,
        status=status,
        notes=notes,
    )
    db.add(log)


def _get_order_products_summary(order: Order) -> List[Dict[str, Any]]:
    """Pobierz podsumowanie produktow z zamowienia dla zwrotu."""
    items = []
    for product in order.products:
        items.append({
            "ean": product.ean,
            "name": product.name,
            "quantity": product.quantity,
            "product_size_id": product.product_size_id,
        })
    return items


def _send_return_notification(return_record: Return) -> bool:
    """
    Wyslij powiadomienie Messenger o nowym zwrocie.
    
    Format: Klient [nazwa], zglosil zwrot [przedmioty zwrotu]
    """
    try:
        items = json.loads(return_record.items_json) if return_record.items_json else []
        items_text = ", ".join([
            f"{item.get('name', 'Nieznany produkt')} x{item.get('quantity', 1)}"
            for item in items
        ])
        
        message = (
            f"[ZWROT] Klient {return_record.customer_name or 'Nieznany'} "
            f"zglosil zwrot: {items_text}"
        )
        
        if return_record.return_tracking_number:
            message += f"\nNumer sledzenia: {return_record.return_tracking_number}"
        
        success = send_messenger(message)
        if success:
            logger.info(f"Wyslano powiadomienie o zwrocie #{return_record.id}")
        else:
            logger.warning(f"Nie udalo sie wyslac powiadomienia o zwrocie #{return_record.id}")
        
        return success
    except Exception as e:
        logger.error(f"Blad wysylania powiadomienia o zwrocie: {e}")
        return False


def create_return_from_order(order: Order, tracking_number: str = None, allegro_return_id: str = None) -> Optional[Return]:
    """
    Utworz rekord zwrotu na podstawie zamowienia.
    
    Args:
        order: Obiekt zamowienia
        tracking_number: Numer sledzenia paczki zwrotnej (opcjonalnie)
        allegro_return_id: ID zwrotu z Allegro API (opcjonalnie)
    
    Returns:
        Utworzony obiekt Return lub None jesli zwrot juz istnieje
    """
    with get_session() as db:
        # Sprawdz czy zwrot dla tego zamowienia juz istnieje
        existing = db.query(Return).filter(Return.order_id == order.order_id).first()
        if existing:
            logger.info(f"Zwrot dla zamowienia {order.order_id} juz istnieje (ID: {existing.id})")
            return existing
        
        # Pobierz produkty z zamowienia
        items = _get_order_products_summary(order)
        
        # Utworz rekord zwrotu
        return_record = Return(
            order_id=order.order_id,
            status=RETURN_STATUS_PENDING,
            customer_name=order.customer_name,
            items_json=json.dumps(items, ensure_ascii=False),
            return_tracking_number=tracking_number,
            allegro_return_id=allegro_return_id,
        )
        db.add(return_record)
        db.flush()  # Aby uzyskac ID
        
        # Dodaj wpis do historii
        _add_return_status_log(
            db, 
            return_record.id, 
            RETURN_STATUS_PENDING,
            f"Utworzono zwrot dla zamowienia {order.order_id}"
        )
        
        db.commit()
        logger.info(f"Utworzono zwrot #{return_record.id} dla zamowienia {order.order_id}")
        
        return return_record


def check_baselinker_order_returns() -> Dict[str, int]:
    """
    Sprawdz zwroty przez BaseLinker getOrderReturns API.
    
    To jest glowne zrodlo danych o zwrotach - BaseLinker synchronizuje
    zwroty z Allegro automatycznie i udostepnia je przez to API.
    
    Returns:
        Slownik z liczba: created, existing, updated, errors
    """
    stats = {"created": 0, "existing": 0, "updated": 0, "errors": 0}
    
    try:
        api_url = "https://api.baselinker.com/connector.php"
        headers = {"X-BLToken": settings.API_TOKEN}
        
        # Pobierz zwroty z ostatnich 30 dni
        from datetime import datetime, timedelta
        date_from = int((datetime.now() - timedelta(days=30)).timestamp())
        
        params = {
            "method": "getOrderReturns",
            "parameters": json.dumps({
                "date_from": date_from,
            })
        }
        
        response = requests.post(api_url, headers=headers, data=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        if data.get("status") != "SUCCESS":
            logger.error(f"Blad BaseLinker getOrderReturns: {data.get('error_message', 'Nieznany blad')}")
            return stats
        
        returns_data = data.get("returns", [])
        logger.info(f"Znaleziono {len(returns_data)} zwrotow w BaseLinker")
        
        with get_session() as db:
            for return_data in returns_data:
                bl_return_id = return_data.get("return_id")
                order_id = str(return_data.get("order_id"))
                
                try:
                    # Sprawdz czy zwrot juz istnieje
                    existing = db.query(Return).filter(
                        Return.order_id == order_id
                    ).first()
                    
                    if existing:
                        # Aktualizuj status jesli sie zmienil
                        # ALE nie cofaj statusu delivered/completed na nizszy!
                        fulfillment_status = return_data.get("fulfillment_status", 0)
                        new_status = _map_baselinker_fulfillment_status(fulfillment_status)
                        
                        # Nie cofaj statusu delivered/completed
                        status_order = [RETURN_STATUS_PENDING, RETURN_STATUS_IN_TRANSIT, 
                                       RETURN_STATUS_DELIVERED, RETURN_STATUS_COMPLETED]
                        current_idx = status_order.index(existing.status) if existing.status in status_order else -1
                        new_idx = status_order.index(new_status) if new_status in status_order else -1
                        
                        # Aktualizuj tylko jesli nowy status jest "wyzszy" lub to anulowanie
                        if new_status == RETURN_STATUS_CANCELLED or (new_idx > current_idx and current_idx >= 0):
                            old_status = existing.status
                            existing.status = new_status
                            
                            # Aktualizuj numer sledzenia jesli pojawil sie nowy
                            if return_data.get("delivery_package_nr") and not existing.return_tracking_number:
                                existing.return_tracking_number = return_data.get("delivery_package_nr")
                                existing.return_carrier = return_data.get("delivery_package_module")
                            
                            _add_return_status_log(
                                db, existing.id, new_status,
                                f"Aktualizacja z BaseLinker (fulfillment_status={fulfillment_status})"
                            )
                            stats["updated"] += 1
                            logger.info(f"Zaktualizowano zwrot #{existing.id}: {old_status} -> {new_status}")
                        else:
                            # Tylko aktualizuj numer sledzenia jesli brakuje
                            if return_data.get("delivery_package_nr") and not existing.return_tracking_number:
                                existing.return_tracking_number = return_data.get("delivery_package_nr")
                                existing.return_carrier = return_data.get("delivery_package_module")
                            stats["existing"] += 1
                        continue
                    
                    # Sprawdz czy zamowienie istnieje w bazie
                    order = db.query(Order).filter(Order.order_id == order_id).first()
                    if not order:
                        logger.debug(f"Zamowienie {order_id} nie istnieje w bazie - pomijam zwrot")
                        continue
                    
                    # Pobierz produkty
                    items = []
                    for product in return_data.get("products", []):
                        items.append({
                            "ean": product.get("ean"),
                            "name": product.get("name"),
                            "quantity": product.get("quantity", 1),
                            "reason_id": product.get("return_reason_id"),
                        })
                    
                    # Okresl status na podstawie fulfillment_status
                    fulfillment_status = return_data.get("fulfillment_status", 0)
                    initial_status = _map_baselinker_fulfillment_status(fulfillment_status)
                    
                    # Utworz rekord zwrotu
                    return_record = Return(
                        order_id=order_id,
                        status=initial_status,
                        customer_name=return_data.get("delivery_fullname") or order.customer_name,
                        items_json=json.dumps(items, ensure_ascii=False),
                        return_tracking_number=return_data.get("delivery_package_nr"),
                        return_carrier=return_data.get("delivery_package_module"),
                        allegro_return_id=return_data.get("external_order_id"),  # Allegro return ID
                        notes=f"BaseLinker return_id: {bl_return_id}, ref: {return_data.get('reference_number')}"
                    )
                    db.add(return_record)
                    db.flush()
                    
                    # Dodaj wpis do historii
                    _add_return_status_log(
                        db, return_record.id, initial_status,
                        f"Wykryto zwrot w BaseLinker (return_id={bl_return_id}, ref={return_data.get('reference_number')})"
                    )
                    
                    # Ustaw status zamowienia na 'zwrot'
                    from .orders import add_order_status
                    add_order_status(
                        db, order_id, "zwrot",
                        notes=f"Wykryto zwrot w BaseLinker (return_id={bl_return_id})"
                    )
                    
                    stats["created"] += 1
                    logger.info(f"Utworzono zwrot #{return_record.id} dla zamowienia {order_id}")
                    
                except Exception as e:
                    logger.error(f"Blad przetwarzania zwrotu BL#{bl_return_id}: {e}")
                    stats["errors"] += 1
            
            db.commit()
        
    except Exception as e:
        logger.error(f"Blad sprawdzania BaseLinker getOrderReturns: {e}")
        stats["errors"] += 1
    
    return stats


def _map_baselinker_fulfillment_status(fulfillment_status: int) -> str:
    """
    Mapuj BaseLinker fulfillment_status na wewnetrzny status zwrotu.
    
    BaseLinker fulfillment_status:
    0 - active (nowy zwrot, paczka jeszcze nie nadana)
    5 - accepted (zaakceptowany zwrot, paczka moze byc w drodze)
    1 - done (zakonczony - refund wyslany)
    2 - canceled (anulowany)
    
    UWAGA: fulfillment_status=5 (accepted) NIE oznacza ze paczka fizycznie dotarla!
    To tylko oznacza ze sprzedawca zaakceptowal zwrot.
    Status delivered ustawiamy tylko na podstawie trackingu paczki.
    """
    status_map = {
        0: RETURN_STATUS_PENDING,     # active - nowy zwrot
        5: RETURN_STATUS_IN_TRANSIT,  # accepted - w drodze (NIE delivered!)
        1: RETURN_STATUS_COMPLETED,   # done - zakonczony
        2: RETURN_STATUS_CANCELLED,   # canceled
    }
    return status_map.get(fulfillment_status, RETURN_STATUS_PENDING)


def check_allegro_customer_returns() -> Dict[str, int]:
    """
    Sprawdz zwroty bezposrednio z Allegro Customer Returns API.
    
    Uzupelniajace zrodlo danych - BaseLinker nie zawsze synchronizuje
    zwroty z Allegro. Ta funkcja odpytuje Allegro bezposrednio
    i tworzy brakujace rekordy Return + ustawia status 'zwrot' na zamowieniu.
    
    Returns:
        Slownik z liczba: created, existing, updated, errors
    """
    from .settings_store import settings_store
    
    stats = {"created": 0, "existing": 0, "updated": 0, "errors": 0}
    
    try:
        access_token = settings_store.settings.ALLEGRO_ACCESS_TOKEN
        if not access_token:
            logger.warning("Brak tokenu Allegro - pomijam sprawdzanie Customer Returns")
            return stats
        
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.allegro.beta.v1+json"
        }
        
        # Pobierz wszystkie zwroty (ostatnie 100)
        response = requests.get(
            "https://api.allegro.pl/order/customer-returns?limit=100",
            headers=headers,
            timeout=30
        )
        response.raise_for_status()
        data = response.json()
        
        customer_returns = data.get("customerReturns", [])
        logger.info(f"Znaleziono {len(customer_returns)} zwrotow w Allegro Customer Returns API")
        
        with get_session() as db:
            for return_data in customer_returns:
                allegro_return_id = return_data.get("id")
                allegro_order_id = return_data.get("orderId")  # external_order_id w naszej bazie
                allegro_status = return_data.get("status")
                
                try:
                    # Sprawdz czy zwrot juz istnieje po allegro_return_id
                    existing = db.query(Return).filter(
                        Return.allegro_return_id == allegro_return_id
                    ).first()
                    
                    if existing:
                        # Aktualizuj status jesli sie zmienil
                        new_status = _map_allegro_return_status(allegro_status)
                        if existing.status != new_status and new_status in [RETURN_STATUS_DELIVERED, RETURN_STATUS_COMPLETED]:
                            old_status = existing.status
                            existing.status = new_status
                            _add_return_status_log(
                                db, existing.id, new_status,
                                f"Aktualizacja z Allegro: {allegro_status}"
                            )
                            stats["updated"] += 1
                            logger.info(f"Zaktualizowano zwrot #{existing.id}: {old_status} -> {new_status}")
                        else:
                            stats["existing"] += 1
                        continue
                    
                    # Znajdz zamowienie po external_order_id
                    order = db.query(Order).filter(
                        Order.external_order_id == allegro_order_id
                    ).first()
                    
                    if not order:
                        logger.debug(f"Zamowienie Allegro {allegro_order_id} nie istnieje w bazie - pomijam")
                        continue
                    
                    # Pobierz dane paczki zwrotnej
                    parcels = return_data.get("parcels", [])
                    return_tracking = None
                    return_carrier = None
                    if parcels:
                        parcel = parcels[0]
                        return_tracking = parcel.get("waybill")
                        return_carrier = parcel.get("carrierId")
                    
                    # Pobierz produkty
                    items = []
                    for item in return_data.get("items", []):
                        items.append({
                            "name": item.get("name"),
                            "quantity": item.get("quantity", 1),
                            "reason": item.get("reason", {}).get("type"),
                            "comment": item.get("reason", {}).get("userComment"),
                        })
                    
                    # Okresl poczatkowy status
                    initial_status = _map_allegro_return_status(allegro_status)
                    
                    # Utworz rekord zwrotu
                    buyer = return_data.get("buyer", {})
                    return_record = Return(
                        order_id=order.order_id,
                        status=initial_status,
                        customer_name=buyer.get("login") or order.customer_name,
                        items_json=json.dumps(items, ensure_ascii=False),
                        return_tracking_number=return_tracking,
                        return_carrier=return_carrier,
                        allegro_return_id=allegro_return_id,
                        notes=f"Allegro ref: {return_data.get('referenceNumber')}"
                    )
                    db.add(return_record)
                    db.flush()
                    
                    # Dodaj wpis do historii
                    _add_return_status_log(
                        db, return_record.id, initial_status,
                        f"Wykryto zwrot w Allegro (ref: {return_data.get('referenceNumber')}, status: {allegro_status})"
                    )
                    
                    # Ustaw status zamowienia na 'zwrot'
                    from .orders import add_order_status
                    add_order_status(
                        db, order.order_id, "zwrot",
                        notes=f"Wykryto zwrot w Allegro Customer Returns (ref: {return_data.get('referenceNumber')})"
                    )
                    
                    stats["created"] += 1
                    logger.info(f"Utworzono zwrot #{return_record.id} dla zamowienia {order.order_id} (Allegro {allegro_order_id})")
                    
                except Exception as e:
                    logger.error(f"Blad przetwarzania zwrotu Allegro {allegro_return_id}: {e}")
                    stats["errors"] += 1
            
            db.commit()
        
    except Exception as e:
        logger.error(f"Blad sprawdzania Allegro Customer Returns: {e}")
        stats["errors"] += 1
    
    return stats


def _map_allegro_return_status(allegro_status: str) -> str:
    """Mapuj status Allegro na wewnetrzny status zwrotu."""
    # Statusy Allegro: CREATED, WAITING_FOR_PARCEL, PARCEL_IN_TRANSIT, 
    # PARCEL_DELIVERED, ACCEPTED, REJECTED, COMMISSION_REFUNDED, FINISHED
    status_map = {
        "CREATED": RETURN_STATUS_PENDING,
        "WAITING_FOR_PARCEL": RETURN_STATUS_PENDING,
        "PARCEL_IN_TRANSIT": RETURN_STATUS_IN_TRANSIT,
        "PARCEL_DELIVERED": RETURN_STATUS_DELIVERED,
        "ACCEPTED": RETURN_STATUS_COMPLETED,
        "COMMISSION_REFUNDED": RETURN_STATUS_COMPLETED,
        "FINISHED": RETURN_STATUS_COMPLETED,
        "REJECTED": RETURN_STATUS_CANCELLED,
    }
    return status_map.get(allegro_status, RETURN_STATUS_PENDING)


def check_baselinker_returns() -> Dict[str, int]:
    """
    Sprawdz zamowienia ze statusem Zwrot w BaseLinker i utworz rekordy zwrotow.
    
    Returns:
        Slownik z liczba: created, existing, errors
    """
    stats = {"created": 0, "existing": 0, "errors": 0}
    
    try:
        api_url = "https://api.baselinker.com/connector.php"
        headers = {"X-BLToken": settings.API_TOKEN}
        
        params = {
            "method": "getOrders",
            "parameters": json.dumps({
                "status_id": BASELINKER_RETURN_STATUS_ID,
                "get_unconfirmed_orders": False,
            })
        }
        
        response = requests.post(api_url, headers=headers, data=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        if data.get("status") != "SUCCESS":
            logger.error(f"Blad BaseLinker API: {data.get('error_message', 'Nieznany blad')}")
            return stats
        
        orders_data = data.get("orders", [])
        logger.info(f"Znaleziono {len(orders_data)} zamowien ze statusem Zwrot")
        
        with get_session() as db:
            for order_data in orders_data:
                order_id = str(order_data.get("order_id"))
                
                try:
                    # Sprawdz czy zwrot juz istnieje
                    existing = db.query(Return).filter(Return.order_id == order_id).first()
                    if existing:
                        stats["existing"] += 1
                        continue
                    
                    # Pobierz zamowienie z naszej bazy
                    order = db.query(Order).filter(Order.order_id == order_id).first()
                    if not order:
                        logger.warning(f"Zamowienie {order_id} nie istnieje w bazie - pomijam")
                        stats["errors"] += 1
                        continue
                    
                    # Pobierz produkty
                    items = []
                    for product in order_data.get("products", []):
                        items.append({
                            "ean": product.get("ean"),
                            "name": product.get("name"),
                            "quantity": product.get("quantity", 1),
                        })
                    
                    # Utworz rekord zwrotu
                    return_record = Return(
                        order_id=order_id,
                        status=RETURN_STATUS_PENDING,
                        customer_name=order_data.get("delivery_fullname") or order.customer_name,
                        items_json=json.dumps(items, ensure_ascii=False),
                        return_tracking_number=order_data.get("delivery_package_nr"),
                        return_carrier=order_data.get("delivery_package_module"),
                    )
                    db.add(return_record)
                    db.flush()
                    
                    # Dodaj wpis do historii
                    _add_return_status_log(
                        db, 
                        return_record.id, 
                        RETURN_STATUS_PENDING,
                        f"Wykryto zwrot w BaseLinker (status_id={BASELINKER_RETURN_STATUS_ID})"
                    )
                    
                    stats["created"] += 1
                    logger.info(f"Utworzono zwrot #{return_record.id} dla zamowienia {order_id}")
                    
                except Exception as e:
                    logger.error(f"Blad przetwarzania zamowienia {order_id}: {e}")
                    stats["errors"] += 1
            
            db.commit()
        
    except Exception as e:
        logger.error(f"Blad sprawdzania zwrotow w BaseLinker: {e}")
        stats["errors"] += 1
    
    return stats


def send_pending_return_notifications() -> Dict[str, int]:
    """
    Wyslij powiadomienia Messenger dla zwrotow bez powiadomienia.
    
    Returns:
        Slownik z liczba: sent, failed
    """
    stats = {"sent": 0, "failed": 0}
    
    with get_session() as db:
        pending_returns = db.query(Return).filter(
            Return.messenger_notified == False
        ).all()
        
        for return_record in pending_returns:
            success = _send_return_notification(return_record)
            if success:
                return_record.messenger_notified = True
                stats["sent"] += 1
            else:
                stats["failed"] += 1
        
        db.commit()
    
    return stats


def track_return_parcel(return_id: int) -> Optional[str]:
    """
    Sledz paczke zwrotna przez Allegro API.
    
    Args:
        return_id: ID zwrotu
        
    Returns:
        Aktualny status przesylki lub None
    """
    from .settings_store import settings_store
    
    with get_session() as db:
        return_record = db.query(Return).filter(Return.id == return_id).first()
        if not return_record:
            logger.warning(f"Zwrot #{return_id} nie istnieje")
            return None
        
        if not return_record.return_tracking_number:
            logger.warning(f"Zwrot #{return_id} nie ma numeru sledzenia")
            return None
        
        # Sprawdz token Allegro
        access_token = settings_store.settings.ALLEGRO_ACCESS_TOKEN
        if not access_token:
            logger.error("Brak tokena dostepu Allegro")
            return None
        
        try:
            # Uzyj Allegro API do sledzenia
            carrier_id = _map_carrier_to_allegro(return_record.return_carrier)
            if not carrier_id:
                carrier_id = "INPOST"  # Domyslnie InPost
            
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.allegro.public.v1+json",
            }
            
            url = f"https://api.allegro.pl/order/carriers/{carrier_id}/tracking"
            params = {"waybill": return_record.return_tracking_number}
            
            response = requests.get(url, headers=headers, params=params, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                waybills = data.get("waybills", [])
                if waybills:
                    tracking_details = waybills[0].get("trackingDetails", {})
                    statuses = tracking_details.get("statuses", [])
                    if statuses:
                        # Ostatni status jest na koncu listy
                        latest_status = statuses[-1].get("code")
                        logger.debug(f"Zwrot #{return_id} - status paczki: {latest_status}")
                        return latest_status
            else:
                logger.warning(f"Blad Allegro tracking API: {response.status_code} - {response.text[:200]}")
            
        except Exception as e:
            logger.error(f"Blad sledzenia paczki zwrotnej: {e}")
        
        return None


def _map_carrier_to_allegro(carrier_name: str) -> Optional[str]:
    """Mapuj nazwe przewoznika na ID w Allegro API."""
    if not carrier_name:
        return None
    
    carrier_lower = carrier_name.lower()
    
    CARRIER_MAP = {
        "inpost": "INPOST",
        "paczkomat": "INPOST",
        "dpd": "DPD",
        "dhl": "DHL",
        "ups": "UPS",
        "fedex": "FEDEX",
        "gls": "GLS",
        "pocztex": "POCZTA_POLSKA",
        "poczta": "POCZTA_POLSKA",
    }
    
    for key, value in CARRIER_MAP.items():
        if key in carrier_lower:
            return value
    
    return "ALLEGRO"


def check_and_update_return_statuses() -> Dict[str, int]:
    """
    Sprawdz statusy paczek zwrotnych i zaktualizuj rekordy.
    
    Logika:
    - Jesli status przesylki to DELIVERED -> ustaw return.status = delivered
    - Jesli paczka dostarczona i stock_restored = False -> przywroc stan
    
    Returns:
        Slownik z liczba: checked, updated, errors
    """
    stats = {"checked": 0, "updated": 0, "errors": 0}
    
    with get_session() as db:
        # Pobierz zwroty w statusie pending lub in_transit z numerem sledzenia
        active_returns = db.query(Return).filter(
            Return.status.in_([RETURN_STATUS_PENDING, RETURN_STATUS_IN_TRANSIT]),
            Return.return_tracking_number.isnot(None)
        ).all()
        
        for return_record in active_returns:
            stats["checked"] += 1
            
            try:
                parcel_status = track_return_parcel(return_record.id)
                
                if parcel_status:
                    # Mapuj status Allegro na nasz status
                    if parcel_status in ["DELIVERED", "PICKED_UP"]:
                        if return_record.status != RETURN_STATUS_DELIVERED:
                            return_record.status = RETURN_STATUS_DELIVERED
                            _add_return_status_log(
                                db,
                                return_record.id,
                                RETURN_STATUS_DELIVERED,
                                f"Paczka zwrotna dostarczona (status: {parcel_status})"
                            )
                            stats["updated"] += 1
                            logger.info(f"Zwrot #{return_record.id} - paczka dostarczona")
                    
                    elif parcel_status in ["IN_TRANSIT", "OUT_FOR_DELIVERY", "COLLECTED"]:
                        if return_record.status == RETURN_STATUS_PENDING:
                            return_record.status = RETURN_STATUS_IN_TRANSIT
                            _add_return_status_log(
                                db,
                                return_record.id,
                                RETURN_STATUS_IN_TRANSIT,
                                f"Paczka w drodze (status: {parcel_status})"
                            )
                            stats["updated"] += 1
                            logger.info(f"Zwrot #{return_record.id} - paczka w drodze")
                
            except Exception as e:
                logger.error(f"Blad sprawdzania statusu zwrotu #{return_record.id}: {e}")
                stats["errors"] += 1
        
        db.commit()
    
    return stats


def restore_stock_for_return(return_id: int) -> bool:
    """
    Przywroc stan magazynowy dla dostarczonego zwrotu.
    
    Args:
        return_id: ID zwrotu
        
    Returns:
        True jesli stan zostal przywrocony, False w przeciwnym razie
    """
    with get_session() as db:
        return_record = db.query(Return).filter(Return.id == return_id).first()
        
        if not return_record:
            logger.error(f"Zwrot #{return_id} nie istnieje")
            return False
        
        if return_record.stock_restored:
            logger.info(f"Stan dla zwrotu #{return_id} juz zostal przywrocony")
            return True
        
        if return_record.status not in [RETURN_STATUS_DELIVERED, RETURN_STATUS_COMPLETED]:
            logger.warning(f"Zwrot #{return_id} nie jest w statusie delivered - nie mozna przywrocic stanu")
            return False
        
        try:
            items = json.loads(return_record.items_json) if return_record.items_json else []
            
            restored_items = []
            for item in items:
                ean = item.get("ean")
                quantity = item.get("quantity", 1)
                product_size_id = item.get("product_size_id")
                
                # Znajdz ProductSize po EAN, ID lub przez auction_id z zamowienia
                product_size = None
                
                # 1. Po product_size_id
                if product_size_id:
                    product_size = db.query(ProductSize).filter(ProductSize.id == product_size_id).first()
                
                # 2. Po EAN
                if not product_size and ean:
                    product_size = db.query(ProductSize).filter(ProductSize.barcode == ean).first()
                
                # 3. Przez auction_id z OrderProduct -> AllegroOffer
                if not product_size and return_record.order_id:
                    # Znajdz OrderProduct z tym EAN w tym zamowieniu
                    order_product = db.query(OrderProduct).filter(
                        OrderProduct.order_id == return_record.order_id,
                        OrderProduct.ean == ean
                    ).first()
                    
                    if order_product and order_product.auction_id:
                        allegro_offer = db.query(AllegroOffer).filter(
                            AllegroOffer.offer_id == order_product.auction_id
                        ).first()
                        if allegro_offer and allegro_offer.product_size_id:
                            product_size = db.query(ProductSize).filter(
                                ProductSize.id == allegro_offer.product_size_id
                            ).first()
                            if product_size:
                                logger.info(f"Znaleziono ProductSize przez auction_id: {order_product.auction_id} -> {product_size.id}")
                
                if product_size:
                    old_qty = product_size.quantity or 0
                    product_size.quantity = old_qty + quantity
                    restored_items.append(f"{item.get('name', 'Produkt')} +{quantity} (bylo: {old_qty})")
                    logger.info(f"Przywrocono stan: {product_size.barcode} +{quantity} (teraz: {product_size.quantity})")
                else:
                    logger.warning(f"Nie znaleziono produktu EAN={ean}, product_size_id={product_size_id}")
            
            if restored_items:
                return_record.stock_restored = True
                return_record.status = RETURN_STATUS_COMPLETED
                _add_return_status_log(
                    db,
                    return_record.id,
                    RETURN_STATUS_COMPLETED,
                    f"Przywrocono stan: {', '.join(restored_items)}"
                )
                db.commit()
                
                # Wyslij powiadomienie o przywroceniu stanu
                message = f"[ZWROT ZAKONCZONY] Zamowienie {return_record.order_id}\nPrzywrocono stan: {', '.join(restored_items)}"
                send_messenger(message)
                
                logger.info(f"Zakonczono obsluge zwrotu #{return_id}")
                return True
            else:
                logger.warning(f"Nie znaleziono produktow do przywrocenia dla zwrotu #{return_id}")
                return False
            
        except Exception as e:
            logger.error(f"Blad przywracania stanu dla zwrotu #{return_id}: {e}")
            db.rollback()
            return False


def process_delivered_returns() -> Dict[str, int]:
    """
    Przetworz dostarczone zwroty - przywroc stany magazynowe.
    
    Returns:
        Slownik z liczba: processed, skipped, errors
    """
    stats = {"processed": 0, "skipped": 0, "errors": 0}
    
    with get_session() as db:
        delivered_returns = db.query(Return).filter(
            Return.status == RETURN_STATUS_DELIVERED,
            Return.stock_restored == False
        ).all()
        
        for return_record in delivered_returns:
            try:
                if restore_stock_for_return(return_record.id):
                    stats["processed"] += 1
                else:
                    stats["skipped"] += 1
            except Exception as e:
                logger.error(f"Blad przetwarzania zwrotu #{return_record.id}: {e}")
                stats["errors"] += 1
    
    return stats


def sync_returns() -> Dict[str, Any]:
    """
    Glowna funkcja synchronizacji zwrotow.
    
    Wykonuje:
    1. Sprawdzenie BaseLinker getOrderReturns API
    2. Sprawdzenie Allegro Customer Returns API (uzupelniajace zrodlo)
    3. Wyslanie powiadomien Messenger
    4. Sprawdzenie statusow paczek zwrotnych (backup tracking)
    5. Przetworzenie dostarczonych zwrotow (przywrocenie stanow)
    
    Returns:
        Slownik ze statystykami wszystkich operacji
    """
    logger.info("Rozpoczynam synchronizacje zwrotow...")
    
    results = {
        "baselinker_returns": check_baselinker_order_returns(),
        "allegro_returns": check_allegro_customer_returns(),
        "notifications": send_pending_return_notifications(),
        "tracking_update": check_and_update_return_statuses(),
        "stock_restore": process_delivered_returns(),
    }
    
    logger.info(f"Synchronizacja zwrotow zakonczona: {results}")
    return results


def get_return_by_order_id(order_id: str) -> Optional[Return]:
    """Pobierz zwrot po ID zamowienia."""
    with get_session() as db:
        return db.query(Return).filter(Return.order_id == order_id).first()


def get_returns_list(status: str = None, limit: int = 50) -> List[Return]:
    """Pobierz liste zwrotow z opcjonalnym filtrem statusu."""
    with get_session() as db:
        query = db.query(Return)
        if status:
            query = query.filter(Return.status == status)
        return query.order_by(desc(Return.created_at)).limit(limit).all()


def mark_return_as_delivered(return_id: int) -> bool:
    """
    Reczne oznaczenie zwrotu jako dostarczonego (gdy paczka jest u nas).
    
    Args:
        return_id: ID zwrotu
        
    Returns:
        True jesli sukces
    """
    with get_session() as db:
        return_record = db.query(Return).filter(Return.id == return_id).first()
        
        if not return_record:
            return False
        
        if return_record.status == RETURN_STATUS_DELIVERED:
            return True
        
        return_record.status = RETURN_STATUS_DELIVERED
        _add_return_status_log(
            db,
            return_record.id,
            RETURN_STATUS_DELIVERED,
            "Reczne oznaczenie jako dostarczone"
        )
        db.commit()
        
        logger.info(f"Zwrot #{return_id} oznaczony jako dostarczony")
        return True


def process_refund(
    order_id: str, 
    delivery_cost_covered: bool = True,
    reason: str = None
) -> Tuple[bool, str]:
    """
    Przetworz zwrot pieniedzy dla zamowienia.
    
    Ta funkcja:
    1. Sprawdza czy zwrot istnieje w bazie i ma status delivered
    2. Pobiera allegro_return_id
    3. Wywoluje Allegro API aby zainicjowac zwrot pieniedzy
    4. Aktualizuje status zwrotu w bazie na completed
    
    UWAGA: Operacja jest NIEODWRACALNA!
    
    Args:
        order_id: ID zamowienia
        delivery_cost_covered: Czy zwrocic koszt dostawy
        reason: Opcjonalny komentarz
        
    Returns:
        Tuple (sukces, komunikat)
    """
    from .settings_store import settings_store
    from . import allegro_api
    
    with get_session() as db:
        # Znajdz zwrot dla zamowienia
        return_record = db.query(Return).filter(Return.order_id == order_id).first()
        
        if not return_record:
            return False, f"Nie znaleziono zwrotu dla zamowienia {order_id}"
        
        # Sprawdz status - musi byc delivered
        if return_record.status not in (RETURN_STATUS_DELIVERED, RETURN_STATUS_IN_TRANSIT):
            return False, f"Zwrot musi byc w statusie 'delivered' lub 'in_transit'. Aktualny status: {return_record.status}"
        
        # Sprawdz czy mamy allegro_return_id
        if not return_record.allegro_return_id:
            return False, "Brak ID zwrotu Allegro - zwrot nie pochodzi z Allegro lub nie zostal zsynchronizowany"
        
        # Pobierz token Allegro
        access_token = settings_store.settings.ALLEGRO_ACCESS_TOKEN
        if not access_token:
            return False, "Brak tokenu Allegro - zaloguj sie do Allegro"
        
        # Wywolaj API Allegro
        success, message, response_data = allegro_api.initiate_refund(
            access_token=access_token,
            return_id=return_record.allegro_return_id,
            delivery_cost_covered=delivery_cost_covered,
            reason=reason
        )
        
        if success:
            # Aktualizuj status w bazie
            return_record.status = RETURN_STATUS_COMPLETED
            _add_return_status_log(
                db,
                return_record.id,
                RETURN_STATUS_COMPLETED,
                f"Zwrot pieniedzy zainicjowany przez Allegro API. {reason or ''}"
            )
            db.commit()
            
            logger.info(f"Zwrot pieniedzy dla zamowienia {order_id} przetworzony pomyslnie")
        else:
            logger.error(f"Blad zwrotu pieniedzy dla zamowienia {order_id}: {message}")
        
        return success, message


def check_refund_eligibility(order_id: str) -> Tuple[bool, str, Optional[Dict]]:
    """
    Sprawdz czy zamowienie kwalifikuje sie do zwrotu pieniedzy.
    
    Zwraca szczegoly o kwocie do zwrotu i statusie.
    
    Args:
        order_id: ID zamowienia
        
    Returns:
        Tuple (kwalifikuje_sie, komunikat, szczegoly)
    """
    from .settings_store import settings_store
    from . import allegro_api
    
    with get_session() as db:
        return_record = db.query(Return).filter(Return.order_id == order_id).first()
        
        if not return_record:
            return False, "Brak zwrotu dla tego zamowienia", None
        
        if return_record.status == RETURN_STATUS_COMPLETED:
            return False, "Zwrot juz zostal rozliczony", None
        
        if return_record.status == RETURN_STATUS_CANCELLED:
            return False, "Zwrot zostal anulowany", None
        
        if return_record.status not in (RETURN_STATUS_DELIVERED, RETURN_STATUS_IN_TRANSIT):
            return False, f"Zwrot musi byc w statusie 'delivered' lub 'in_transit'. Aktualny: {return_record.status}", None
        
        if not return_record.allegro_return_id:
            return False, "Brak ID zwrotu Allegro", None
        
        # Pobierz szczegoly z Allegro API
        access_token = settings_store.settings.ALLEGRO_ACCESS_TOKEN
        if not access_token:
            return False, "Brak tokenu Allegro", None
        
        return_data, error = allegro_api.get_customer_return(access_token, return_record.allegro_return_id)
        if error:
            return False, f"Blad pobierania danych z Allegro: {error}", None
        
        can_refund, validation_msg = allegro_api.validate_return_for_refund(return_data)
        
        if not can_refund:
            return False, validation_msg, None
        
        # Przygotuj szczegoly
        refund = return_data.get("refund", {})
        total_value = refund.get("totalValue", {})
        delivery = refund.get("delivery", {})
        
        details = {
            "allegro_status": return_data.get("status"),
            "total_amount": float(total_value.get("amount", 0)),
            "currency": total_value.get("currency", "PLN"),
            "delivery_amount": float(delivery.get("amount", 0)) if delivery else 0,
            "items": return_data.get("items", []),
            "allegro_return_id": return_record.allegro_return_id,
        }
        
        return True, validation_msg, details
