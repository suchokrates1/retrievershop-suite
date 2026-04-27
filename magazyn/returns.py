"""
System obslugi zwrotow produktow.

Ten modul odpowiada za:
- Wykrywanie zwrotow przez Allegro Customer Returns API
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
from .domain.returns import (
    RETURN_STATUS_CANCELLED,
    RETURN_STATUS_COMPLETED,
    RETURN_STATUS_DELIVERED,
    RETURN_STATUS_IN_TRANSIT,
    RETURN_STATUS_PENDING,
    map_allegro_return_status as _map_allegro_return_status,
    map_carrier_to_allegro as _map_carrier_to_allegro,
)
from .models.orders import Order
from .models.returns import Return, ReturnStatusLog
from .notifications import send_messenger
from . import allegro_api

logger = logging.getLogger(__name__)

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
    from .services.return_notifications import get_order_products_summary as _get_order_products_summary_service

    return _get_order_products_summary_service(order)


def _send_return_notification(return_record: Return) -> bool:
    """
    Wyslij powiadomienie Messenger o nowym zwrocie.
    
    Format: Klient [nazwa], zglosil zwrot [przedmioty zwrotu]
    """
    from .services.return_notifications import send_return_notification as _send_return_notification_service

    return _send_return_notification_service(
        return_record,
        send_message=send_messenger,
        log=logger,
    )


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


def check_allegro_customer_returns() -> Dict[str, int]:
    """
    Sprawdz zwroty bezposrednio z Allegro Customer Returns API.
    
    Odpytuje Allegro Customer Returns API i synchronizuje rekordy
    zwrotow do lokalnej bazy.
    
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
        
        from .allegro_api.core import ALLEGRO_USER_AGENT
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.allegro.beta.v1+json",
            "User-Agent": ALLEGRO_USER_AGENT,
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
                        updated = False

                        # Aktualizuj dane paczki jesli pojawily sie w Allegro
                        parcels = return_data.get("parcels", [])
                        if parcels and not existing.return_tracking_number:
                            parcel = parcels[0]
                            waybill = parcel.get("waybill")
                            carrier = parcel.get("carrierId")
                            if waybill:
                                existing.return_tracking_number = waybill
                                existing.return_carrier = carrier
                                updated = True
                                logger.info(f"Zaktualizowano dane paczki zwrotu #{existing.id}: {waybill} ({carrier})")

                        # Aktualizuj status jesli sie zmienil
                        new_status = _map_allegro_return_status(allegro_status)
                        if existing.status != new_status and new_status in [
                            RETURN_STATUS_IN_TRANSIT,
                            RETURN_STATUS_DELIVERED,
                            RETURN_STATUS_COMPLETED,
                            RETURN_STATUS_CANCELLED,
                        ]:
                            old_status = existing.status
                            existing.status = new_status
                            _add_return_status_log(
                                db, existing.id, new_status,
                                f"Aktualizacja z Allegro: {allegro_status}"
                            )
                            updated = True
                            logger.info(f"Zaktualizowano zwrot #{existing.id}: {old_status} -> {new_status}")

                        if updated:
                            stats["updated"] += 1
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
                    from .services.order_status import add_order_status
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
            
            from .allegro_api.core import ALLEGRO_USER_AGENT
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.allegro.public.v1+json",
                "User-Agent": ALLEGRO_USER_AGENT,
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
                    
                    elif parcel_status in ["IN_TRANSIT", "OUT_FOR_DELIVERY", "COLLECTED", "RELEASED_FOR_DELIVERY"]:
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
    from .services.return_stock import restore_stock_for_return as _restore_stock_for_return_service

    return _restore_stock_for_return_service(
        return_id,
        send_message=send_messenger,
        log=logger,
    )


def process_delivered_returns() -> Dict[str, int]:
    """
    Przetworz dostarczone zwroty - przywroc stany magazynowe.
    
    Returns:
        Slownik z liczba: processed, skipped, errors
    """
    from .services.return_stock import process_delivered_returns as _process_delivered_returns_service

    return _process_delivered_returns_service(
        restore_stock=restore_stock_for_return,
        log=logger,
    )


def expire_stale_returns() -> Dict[str, int]:
    """
    Zamknij zwroty, ktore nie zostaly nadane w ciagu 16 dni od zgloszenia.

    Allegro daje kupujacemu 14 dni na nadanie paczki po wypelnieniu formularza.
    Dodajemy 2 dni buforu na opoznienia kurierskie = 16 dni od created_at.
    Jesli zwrot nadal ma status 'pending' i brak tracking number, uznajemy go za wygasly.
    """
    from datetime import timedelta
    from .services.order_status import add_order_status

    stats = {"expired": 0, "errors": 0}
    cutoff = datetime.utcnow() - timedelta(days=16)

    with get_session() as db:
        stale = db.query(Return).filter(
            Return.status == RETURN_STATUS_PENDING,
            Return.return_tracking_number.is_(None),
            Return.created_at < cutoff,
        ).all()

        for ret in stale:
            try:
                ret.status = RETURN_STATUS_CANCELLED
                _add_return_status_log(
                    db, ret.id, RETURN_STATUS_CANCELLED,
                    "Zwrot wygasl - brak nadania przesylki w ciagu 16 dni od zgloszenia",
                )
                add_order_status(
                    db, ret.order_id, "dostarczono",
                    allow_backwards=True,
                    notes="Zwrot wygasl (brak nadania w terminie) - przywrocono status zakonczonego zamowienia",
                )
                stats["expired"] += 1
                logger.info(f"Zwrot #{ret.id} (zamowienie {ret.order_id}) wygasl - brak nadania w 16 dni")
            except Exception as e:
                logger.error(f"Blad wygaszania zwrotu #{ret.id}: {e}")
                stats["errors"] += 1
        db.commit()

    return stats


def sync_returns() -> Dict[str, Any]:
    """
    Glowna funkcja synchronizacji zwrotow.
    
    Wykonuje:
    1. Sprawdzenie Allegro Customer Returns API
    2. Wyslanie powiadomien Messenger
    3. Sprawdzenie statusow paczek zwrotnych (tracking)
    4. Przetworzenie dostarczonych zwrotow (przywrocenie stanow)
    5. Wygaszenie zwrotow bez nadania po 16 dniach
    
    Returns:
        Slownik ze statystykami wszystkich operacji
    """
    logger.info("Rozpoczynam synchronizacje zwrotow...")
    
    results = {
        "allegro_returns": check_allegro_customer_returns(),
        "notifications": send_pending_return_notifications(),
        "tracking_update": check_and_update_return_statuses(),
        "stock_restore": process_delivered_returns(),
        "expired": expire_stale_returns(),
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
    
    with get_session() as db:
        # Znajdz zwrot dla zamowienia
        return_record = db.query(Return).filter(Return.order_id == order_id).first()
        
        if not return_record:
            return False, f"Nie znaleziono zwrotu dla zamowienia {order_id}"
        
        if return_record.refund_processed:
            return False, "Zwrot pieniedzy juz zostal przetworzony"
        
        # Sprawdz status
        allowed = (RETURN_STATUS_DELIVERED, RETURN_STATUS_IN_TRANSIT, RETURN_STATUS_COMPLETED)
        if return_record.status not in allowed:
            return False, f"Zwrot musi byc w statusie 'delivered', 'in_transit' lub 'completed'. Aktualny status: {return_record.status}"
        
        # Sprawdz czy mamy allegro_return_id
        if not return_record.allegro_return_id:
            return False, "Brak ID zwrotu Allegro - zwrot nie pochodzi z Allegro lub nie zostal zsynchronizowany"
        
        # Pobierz token Allegro
        access_token = settings_store.settings.ALLEGRO_ACCESS_TOKEN
        if not access_token:
            return False, "Brak tokenu Allegro - zaloguj sie do Allegro"
        
        # Pobierz external_order_id z zamowienia
        order_record = db.query(Order).filter(Order.order_id == order_id).first()
        if not order_record or not order_record.external_order_id:
            return False, "Brak external_order_id zamowienia - nie mozna zrealizowac zwrotu"

        # Wywolaj API Allegro
        success, message, response_data = allegro_api.initiate_refund(
            access_token=access_token,
            return_id=return_record.allegro_return_id,
            order_external_id=order_record.external_order_id,
            delivery_cost_covered=delivery_cost_covered,
            reason=reason
        )
        
        if success:
            # Aktualizuj status w bazie
            return_record.status = RETURN_STATUS_COMPLETED
            return_record.refund_processed = True
            _add_return_status_log(
                db,
                return_record.id,
                RETURN_STATUS_COMPLETED,
                f"Zwrot pieniedzy zainicjowany przez Allegro API. {reason or ''}"
            )
            db.commit()
            
            logger.info(f"Zwrot pieniedzy dla zamowienia {order_id} przetworzony pomyslnie")
            
            # Wystaw korekte faktury (jesli zamowienie ma fakture wFirma)
            try:
                from .services.invoice_service import generate_correction_invoice
                correction = generate_correction_invoice(
                    order_id=order_id,
                    reason=reason or "Zwrot produktow",
                    return_id=return_record.id,
                    include_delivery=delivery_cost_covered,
                )
                if correction["success"]:
                    logger.info(
                        "Korekta %s wystawiona dla zamowienia %s",
                        correction["invoice_number"], order_id,
                    )
                else:
                    logger.warning(
                        "Nie udalo sie wystawic korekty dla zamowienia %s: %s",
                        order_id, correction["errors"],
                    )
            except Exception as exc:
                logger.error(
                    "Blad wystawiania korekty dla zamowienia %s: %s",
                    order_id, exc,
                )

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
    
    with get_session() as db:
        return_record = db.query(Return).filter(Return.order_id == order_id).first()
        
        if not return_record:
            return False, "Brak zwrotu dla tego zamowienia", None
        
        if return_record.refund_processed:
            return False, "Zwrot pieniedzy juz zostal przetworzony", None
        
        if return_record.status == RETURN_STATUS_CANCELLED:
            return False, "Zwrot zostal anulowany", None
        
        allowed = (RETURN_STATUS_DELIVERED, RETURN_STATUS_IN_TRANSIT, RETURN_STATUS_COMPLETED)
        if return_record.status not in allowed:
            return False, f"Zwrot musi byc w statusie 'delivered', 'in_transit' lub 'completed'. Aktualny: {return_record.status}", None
        
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
        refund = return_data.get("refund") or {}
        total_value = refund.get("totalValue") or {}
        delivery = refund.get("delivery") or {}
        
        total_amount = float(total_value.get("amount", 0))
        currency = total_value.get("currency", "PLN")
        
        # Oblicz z items jesli brak totalValue
        if total_amount <= 0:
            items = return_data.get("items", [])
            for item in items:
                price = item.get("price", {})
                item_amount = float(price.get("amount", 0))
                qty = int(item.get("quantity", 1))
                total_amount += item_amount * qty
                if currency == "PLN":
                    currency = price.get("currency", "PLN")
        
        details = {
            "allegro_status": return_data.get("status"),
            "total_amount": total_amount,
            "currency": currency,
            "delivery_amount": float(delivery.get("amount", 0)) if delivery else 0,
            "items": return_data.get("items", []),
            "allegro_return_id": return_record.allegro_return_id,
        }
        
        return True, validation_msg, details
