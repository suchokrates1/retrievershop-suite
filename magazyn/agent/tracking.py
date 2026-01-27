"""
Modul do sledzenia statusow przesylek.

Wyodrebniony z print_agent.py dla lepszej organizacji kodu.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

import requests

from ..db import sqlite_connect
from ..notifications import send_messenger


logger = logging.getLogger(__name__)


# Mapowanie statusow BaseLinker -> wewnetrzne
TRACKING_STATUS_MAP: Dict[str, str] = {
    "placed": "Nadana",
    "collected": "Podjęta",
    "in_transit": "W drodze",
    "out_for_delivery": "W doręczeniu",
    "ready_to_collect": "Do odbioru",
    "delivered": "Doręczona",
    "returned": "Zwrot",
    "failed": "Nieudana",
    "cancelled": "Anulowana",
    "other": "Inny",
    "unknown": "Nieznany",
}


class TrackingService:
    """
    Serwis do sledzenia statusow przesylek przez BaseLinker API.
    
    Uzycie:
        service = TrackingService(
            api_token="...",
            db_file="...",
            get_order_packages=my_callback
        )
        service.check_tracking_statuses()
    """
    
    BASELINKER_API_URL = "https://api.baselinker.com/connector.php"
    
    def __init__(
        self,
        api_token: str,
        db_file: str,
        get_order_packages: Callable[[int], List[Dict[str, Any]]],
        notify: bool = True
    ):
        """
        Args:
            api_token: Token API BaseLinker
            db_file: Sciezka do pliku bazy SQLite
            get_order_packages: Funkcja zwracajaca liste paczek dla zamowienia
            notify: Czy wysylac powiadomienia Messenger
        """
        self.api_token = api_token
        self.db_file = db_file
        self.get_order_packages = get_order_packages
        self.notify = notify
    
    def _call_baselinker(self, method: str, params: dict) -> dict:
        """Wywoluje API BaseLinker."""
        response = requests.post(
            self.BASELINKER_API_URL,
            headers={"X-BLToken": self.api_token},
            data={"method": method, "parameters": str(params).replace("'", '"')},
            timeout=30,
        )
        response.raise_for_status()
        return response.json()
    
    def check_tracking_statuses(self) -> None:
        """
        Sprawdza statusy sledzenia dla wszystkich aktywnych przesylek.
        
        Pobiera z bazy zamowienia ze statusem 'Wysłano', sprawdza ich 
        statusy przez BaseLinker API i aktualizuje w bazie.
        """
        with sqlite_connect(self.db_file) as conn:
            cur = conn.cursor()
            
            # Pobierz zamowienia do sprawdzenia
            cur.execute("""
                SELECT order_id 
                FROM order_status_log 
                WHERE status = 'Wysłano' 
                  AND tracking_status NOT IN ('Doręczona', 'Zwrot', 'Anulowana')
                  OR tracking_status IS NULL
            """)
            orders_to_check = [row[0] for row in cur.fetchall()]
        
        if not orders_to_check:
            logger.debug("Brak zamowien do sprawdzenia statusu sledzenia")
            return
        
        logger.info("Sprawdzam status sledzenia dla %d zamowien", len(orders_to_check))
        
        for order_id in orders_to_check:
            self._check_order_tracking(order_id)
    
    def _check_order_tracking(self, order_id: int) -> None:
        """Sprawdza status sledzenia pojedynczego zamowienia."""
        try:
            packages = self.get_order_packages(order_id)
        except Exception as exc:
            logger.error("Blad pobierania paczek dla zamowienia %s: %s", order_id, exc)
            return
        
        if not packages:
            logger.debug("Brak paczek dla zamowienia %s", order_id)
            return
        
        for package in packages:
            tracking_number = package.get("courier_package_nr") or package.get("tracking_number")
            courier_code = package.get("courier_code")
            
            if not tracking_number:
                continue
            
            self._check_package_tracking(order_id, tracking_number, courier_code)
    
    def _check_package_tracking(
        self,
        order_id: int,
        tracking_number: str,
        courier_code: Optional[str]
    ) -> None:
        """Sprawdza status sledzenia pojedynczej paczki."""
        try:
            result = self._call_baselinker(
                "getCourierTracking",
                {
                    "tracking_number": tracking_number,
                    "courier_code": courier_code or "",
                },
            )
        except Exception as exc:
            logger.debug("Blad pobierania statusu sledzenia %s: %s", tracking_number, exc)
            return
        
        tracking_data = result.get("tracking", {})
        if not tracking_data:
            return
        
        status_raw = tracking_data.get("status", "unknown")
        status = TRACKING_STATUS_MAP.get(status_raw, f"Nieznany ({status_raw})")
        
        last_update = tracking_data.get("last_update")
        last_location = tracking_data.get("last_location", "")
        
        self._update_tracking_status(
            order_id, tracking_number, status, last_update, last_location
        )
    
    def _update_tracking_status(
        self,
        order_id: int,
        tracking_number: str,
        new_status: str,
        last_update: Optional[str],
        last_location: str
    ) -> None:
        """Aktualizuje status sledzenia w bazie i wysyla powiadomienie."""
        with sqlite_connect(self.db_file) as conn:
            cur = conn.cursor()
            
            # Sprawdz obecny status
            cur.execute(
                "SELECT tracking_status FROM order_status_log WHERE order_id = ?",
                (order_id,),
            )
            row = cur.fetchone()
            old_status = row[0] if row else None
            
            if old_status == new_status:
                return
            
            # Aktualizuj status
            cur.execute(
                """
                UPDATE order_status_log 
                SET tracking_status = ?,
                    tracking_updated_at = ?,
                    tracking_location = ?
                WHERE order_id = ?
                """,
                (
                    new_status,
                    last_update or datetime.now(timezone.utc).isoformat(),
                    last_location,
                    order_id,
                ),
            )
            
            logger.info(
                "Zamowienie %s: status sledzenia %s -> %s (%s)",
                order_id, old_status, new_status, last_location
            )
            
            # Powiadomienie dla waznych statusow
            if self.notify and new_status in ("Doręczona", "Zwrot", "Do odbioru"):
                self._send_tracking_notification(order_id, new_status, last_location)
    
    def _send_tracking_notification(
        self,
        order_id: int,
        status: str,
        location: str
    ) -> None:
        """Wysyla powiadomienie Messenger o zmianie statusu."""
        location_info = f" ({location})" if location else ""
        
        if status == "Doręczona":
            message = f"Przesylka z zamowienia #{order_id} zostala doreczona{location_info}"
        elif status == "Zwrot":
            message = f"Przesylka z zamowienia #{order_id} wraca jako zwrot{location_info}"
        elif status == "Do odbioru":
            message = f"Przesylka z zamowienia #{order_id} czeka na odbior{location_info}"
        else:
            message = f"Zamowienie #{order_id}: status przesylki: {status}{location_info}"
        
        try:
            send_messenger(message)
        except Exception as exc:
            logger.error("Blad wysylania powiadomienia o sledzeniu: %s", exc)


def check_tracking_statuses(
    api_token: str,
    db_file: str,
    get_order_packages: Callable[[int], List[Dict[str, Any]]],
    notify: bool = True
) -> None:
    """
    Funkcja pomocnicza do sprawdzania statusow sledzenia.
    
    Args:
        api_token: Token API BaseLinker
        db_file: Sciezka do pliku bazy SQLite
        get_order_packages: Funkcja zwracajaca liste paczek dla zamowienia
        notify: Czy wysylac powiadomienia Messenger
    """
    service = TrackingService(api_token, db_file, get_order_packages, notify)
    service.check_tracking_statuses()
