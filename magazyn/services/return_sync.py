"""
Serwis synchronizacji zwrotow.

Wyodrebniony z returns.py dla lepszej organizacji i testowalnosci.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests

from ..config import settings
from ..db import get_session
from ..models import Return, Order
from ..notifications import send_return_notification


logger = logging.getLogger(__name__)


# Stale statusow zwrotow
RETURN_STATUS_PENDING = "oczekujacy"
RETURN_STATUS_IN_TRANSIT = "w_drodze"
RETURN_STATUS_DELIVERED = "dostarczony"
RETURN_STATUS_COMPLETED = "zakonczony"
RETURN_STATUS_CANCELLED = "anulowany"

# BaseLinker status ID dla zwrotow
BASELINKER_RETURN_STATUS_ID = 7855


class ReturnSyncService:
    """Serwis do synchronizacji zwrotow z zewnetrznymi zrodlami."""
    
    def __init__(self, db_session=None):
        """
        Args:
            db_session: Opcjonalna sesja bazy danych (dla testowalnosci)
        """
        self._db = db_session
    
    @property
    def db(self):
        """Lazy access to database session."""
        return self._db
    
    def sync_all(self) -> Dict[str, Any]:
        """
        Wykonaj pelna synchronizacje zwrotow.
        
        Wykonuje:
        1. Sprawdzenie BaseLinker getOrderReturns API (glowne zrodlo)
        2. Wyslanie powiadomien Messenger
        3. Sprawdzenie statusow paczek zwrotnych
        4. Przetworzenie dostarczonych zwrotow
        
        Returns:
            Slownik ze statystykami wszystkich operacji
        """
        logger.info("Rozpoczynam pelna synchronizacje zwrotow...")
        
        results = {
            "baselinker_returns": self.check_baselinker_returns(),
            "notifications": self.send_pending_notifications(),
            "tracking_update": self.check_tracking_statuses(),
            "stock_restore": self.process_delivered_returns(),
        }
        
        logger.info(f"Synchronizacja zwrotow zakonczona: {results}")
        return results
    
    def check_baselinker_returns(self) -> Dict[str, int]:
        """
        Sprawdz zwroty w BaseLinker API.
        
        Returns:
            Slownik z liczba: created, existing, errors
        """
        stats = {"created": 0, "existing": 0, "errors": 0}
        
        try:
            api_url = "https://api.baselinker.com/connector.php"
            headers = {"X-BLToken": settings.API_TOKEN}
            
            # Uzyj getOrderReturns API
            params = {
                "method": "getOrderReturns",
                "parameters": json.dumps({
                    "date_from": int((datetime.now().timestamp() - 30 * 24 * 3600)),  # 30 dni wstecz
                })
            }
            
            response = requests.post(api_url, headers=headers, data=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            if data.get("status") != "SUCCESS":
                logger.error(f"Blad BaseLinker API: {data.get('error_message', 'Nieznany blad')}")
                return stats
            
            returns_data = data.get("returns", [])
            logger.info(f"Znaleziono {len(returns_data)} zwrotow w BaseLinker")
            
            with get_session() as db:
                for return_data in returns_data:
                    try:
                        result = self._process_baselinker_return(db, return_data)
                        stats[result] += 1
                    except Exception as e:
                        logger.error(f"Blad przetwarzania zwrotu: {e}")
                        stats["errors"] += 1
                
                db.commit()
                
        except Exception as e:
            logger.error(f"Blad sprawdzania zwrotow BaseLinker: {e}")
            stats["errors"] += 1
        
        return stats
    
    def _process_baselinker_return(
        self, 
        db, 
        return_data: Dict[str, Any]
    ) -> str:
        """
        Przetworz pojedynczy zwrot z BaseLinker.
        
        Returns:
            'created', 'existing', lub 'errors'
        """
        order_id = str(return_data.get("order_id"))
        
        # Sprawdz czy zwrot juz istnieje
        existing = db.query(Return).filter(Return.order_id == order_id).first()
        if existing:
            return "existing"
        
        # Pobierz zamowienie z naszej bazy
        order = db.query(Order).filter(Order.order_id == order_id).first()
        if not order:
            logger.warning(f"Zamowienie {order_id} nie istnieje w bazie - pomijam")
            return "errors"
        
        # Pobierz produkty
        items = []
        for product in return_data.get("products", []):
            items.append({
                "ean": product.get("ean"),
                "name": product.get("name"),
                "quantity": product.get("quantity", 1),
            })
        
        # Utworz rekord zwrotu
        return_record = Return(
            order_id=order_id,
            status=RETURN_STATUS_PENDING,
            customer_name=return_data.get("customer_name") or order.customer_name,
            items_json=json.dumps(items, ensure_ascii=False),
            return_tracking_number=return_data.get("tracking_number"),
            return_carrier=return_data.get("carrier"),
        )
        db.add(return_record)
        db.flush()
        
        logger.info(f"Utworzono zwrot #{return_record.id} dla zamowienia {order_id}")
        return "created"
    
    def send_pending_notifications(self) -> Dict[str, int]:
        """
        Wyslij powiadomienia dla nowych zwrotow.
        
        Returns:
            Slownik z liczba: sent, failed
        """
        stats = {"sent": 0, "failed": 0}
        
        with get_session() as db:
            pending_returns = db.query(Return).filter(
                Return.messenger_notified == False
            ).all()
            
            for return_record in pending_returns:
                try:
                    success = send_return_notification(return_record)
                    if success:
                        return_record.messenger_notified = True
                        stats["sent"] += 1
                    else:
                        stats["failed"] += 1
                except Exception as e:
                    logger.error(f"Blad wysylania powiadomienia dla zwrotu #{return_record.id}: {e}")
                    stats["failed"] += 1
            
            db.commit()
        
        return stats
    
    def check_tracking_statuses(self) -> Dict[str, int]:
        """
        Sprawdz statusy sledzenia paczek zwrotnych.
        
        Returns:
            Slownik z liczba: updated, unchanged, errors
        """
        stats = {"updated": 0, "unchanged": 0, "errors": 0}
        
        with get_session() as db:
            # Pobierz zwroty w tranzycie z numerem sledzenia
            returns_in_transit = db.query(Return).filter(
                Return.status.in_([RETURN_STATUS_PENDING, RETURN_STATUS_IN_TRANSIT]),
                Return.return_tracking_number.isnot(None),
            ).all()
            
            for return_record in returns_in_transit:
                try:
                    new_status = self._check_single_tracking(return_record)
                    if new_status and new_status != return_record.status:
                        return_record.status = new_status
                        stats["updated"] += 1
                    else:
                        stats["unchanged"] += 1
                except Exception as e:
                    logger.error(f"Blad sledzenia zwrotu #{return_record.id}: {e}")
                    stats["errors"] += 1
            
            db.commit()
        
        return stats
    
    def _check_single_tracking(self, return_record: Return) -> Optional[str]:
        """Sprawdz status sledzenia dla pojedynczego zwrotu."""
        from ..settings_store import settings_store
        
        if not return_record.return_tracking_number:
            return None
        
        access_token = settings_store.settings.ALLEGRO_ACCESS_TOKEN
        if not access_token:
            return None
        
        carrier_id = self._map_carrier_to_allegro(return_record.return_carrier)
        if not carrier_id:
            carrier_id = "INPOST"
        
        try:
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
                        latest_status = statuses[-1].get("code")
                        return self._map_tracking_status(latest_status)
        except Exception as e:
            logger.debug(f"Blad sprawdzania trackingu: {e}")
        
        return None
    
    def _map_tracking_status(self, tracking_status: str) -> str:
        """Mapuj status sledzenia na wewnetrzny status zwrotu."""
        delivered_statuses = ["DELIVERED", "PICKED_UP", "READY_FOR_PICKUP"]
        in_transit_statuses = ["IN_TRANSIT", "SENT", "ACCEPTED"]
        
        if tracking_status in delivered_statuses:
            return RETURN_STATUS_DELIVERED
        elif tracking_status in in_transit_statuses:
            return RETURN_STATUS_IN_TRANSIT
        
        return RETURN_STATUS_PENDING
    
    def _map_carrier_to_allegro(self, carrier_name: str) -> Optional[str]:
        """Mapuj nazwe przewoznika na ID w Allegro API."""
        if not carrier_name:
            return None
        
        carrier_lower = carrier_name.lower()
        
        carrier_map = {
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
        
        for key, value in carrier_map.items():
            if key in carrier_lower:
                return value
        
        return None
    
    def process_delivered_returns(self) -> Dict[str, int]:
        """
        Przetworz dostarczone zwroty (przywroc stany magazynowe).
        
        Returns:
            Slownik z liczba: processed, skipped, errors
        """
        stats = {"processed": 0, "skipped": 0, "errors": 0}
        
        with get_session() as db:
            delivered_returns = db.query(Return).filter(
                Return.status == RETURN_STATUS_DELIVERED,
                Return.stock_restored == False,
            ).all()
            
            for return_record in delivered_returns:
                try:
                    success = self._restore_stock_for_return(db, return_record)
                    if success:
                        return_record.stock_restored = True
                        return_record.status = RETURN_STATUS_COMPLETED
                        stats["processed"] += 1
                    else:
                        stats["skipped"] += 1
                except Exception as e:
                    logger.error(f"Blad przywracania stanow dla zwrotu #{return_record.id}: {e}")
                    stats["errors"] += 1
            
            db.commit()
        
        return stats
    
    def _restore_stock_for_return(self, db, return_record: Return) -> bool:
        """
        Przywroc stany magazynowe dla zwrotu.
        
        Returns:
            True jesli sukces
        """
        try:
            items = json.loads(return_record.items_json or "[]")
        except json.JSONDecodeError:
            logger.error(f"Nieprawidlowy JSON dla zwrotu #{return_record.id}")
            return False
        
        if not items:
            logger.warning(f"Brak pozycji dla zwrotu #{return_record.id}")
            return False
        
        from ..db import restore_stock_for_ean
        
        for item in items:
            ean = item.get("ean")
            quantity = item.get("quantity", 1)
            
            if not ean:
                continue
            
            try:
                restore_stock_for_ean(ean, quantity)
                logger.info(f"Przywrocono {quantity} szt. dla EAN {ean}")
            except Exception as e:
                logger.error(f"Blad przywracania dla EAN {ean}: {e}")
        
        return True


def create_return_sync_service() -> ReturnSyncService:
    """Fabryka do tworzenia ReturnSyncService."""
    return ReturnSyncService()
