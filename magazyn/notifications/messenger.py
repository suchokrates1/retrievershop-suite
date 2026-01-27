"""
Modul do wysylania wiadomosci przez Facebook Messenger.

Centralizuje cala logike komunikacji z Messenger API.
"""

import json
import logging
import requests
from typing import Optional, List
from dataclasses import dataclass


logger = logging.getLogger(__name__)

# Stale API
MESSENGER_API_URL = "https://graph.facebook.com/v17.0/me/messages"
DEFAULT_TIMEOUT = 10


@dataclass
class MessengerConfig:
    """Konfiguracja klienta Messenger."""
    access_token: str
    recipient_id: str
    timeout: int = DEFAULT_TIMEOUT


class MessengerClient:
    """
    Klient do wysylania wiadomosci przez Messenger.
    
    Uzycie:
        client = MessengerClient(config)
        client.send_text("Nowe zamowienie!")
        client.send_lines(["Linia 1", "Linia 2", "Linia 3"])
    """
    
    def __init__(self, config: MessengerConfig):
        self.config = config
        self._headers = {
            "Authorization": f"Bearer {config.access_token}",
            "Content-Type": "application/json"
        }
    
    def send_text(self, message: str) -> bool:
        """
        Wysyla pojedyncza wiadomosc tekstowa.
        
        Args:
            message: Tresc wiadomosci
            
        Returns:
            True jesli wyslano pomyslnie
        """
        if not message or not message.strip():
            logger.warning("Proba wyslania pustej wiadomosci")
            return False
        
        payload = {
            "recipient": {"id": self.config.recipient_id},
            "message": {"text": message}
        }
        
        try:
            response = requests.post(
                MESSENGER_API_URL,
                headers=self._headers,
                data=json.dumps(payload),
                timeout=self.config.timeout
            )
            
            if response.status_code == 200:
                logger.debug(f"Wiadomosc wyslana pomyslnie")
                return True
            else:
                logger.error(f"Blad wysylania: {response.status_code} - {response.text}")
                return False
                
        except requests.exceptions.Timeout:
            logger.error("Timeout podczas wysylania wiadomosci")
            return False
        except requests.exceptions.RequestException as e:
            logger.error(f"Blad polaczenia: {e}")
            return False
    
    def send_lines(self, lines: List[str], separator: str = "\n") -> bool:
        """
        Wysyla wiele linii jako jedna wiadomosc.
        
        Args:
            lines: Lista linii do wyslania
            separator: Separator miedzy liniami
            
        Returns:
            True jesli wyslano pomyslnie
        """
        message = separator.join(lines)
        return self.send_text(message)
    
    def send_with_title(self, title: str, lines: List[str]) -> bool:
        """
        Wysyla wiadomosc z tytulem i liniami.
        
        Args:
            title: Tytul/naglowek wiadomosci
            lines: Lista linii tresci
            
        Returns:
            True jesli wyslano pomyslnie
        """
        full_lines = [title, ""] + lines
        return self.send_lines(full_lines)


# Globalna instancja klienta (inicjalizowana przez settings)
_default_client: Optional[MessengerClient] = None


def init_messenger(access_token: str, recipient_id: str, timeout: int = DEFAULT_TIMEOUT):
    """
    Inicjalizuje domyslnego klienta Messenger.
    
    Wywolaj na starcie aplikacji z odpowiednimi credentialami.
    """
    global _default_client
    config = MessengerConfig(
        access_token=access_token,
        recipient_id=recipient_id,
        timeout=timeout
    )
    _default_client = MessengerClient(config)
    logger.info("Zainicjalizowano klienta Messenger")


def get_messenger_client() -> Optional[MessengerClient]:
    """Zwraca domyslnego klienta Messenger."""
    return _default_client


def send_messenger(message: str) -> bool:
    """
    Wysyla wiadomosc przez domyslnego klienta lub bezposrednio przez settings.
    
    Args:
        message: Tresc wiadomosci
        
    Returns:
        True jesli wyslano pomyslnie, False w przeciwnym razie
    """
    # Jesli jest zainicjalizowany klient - uzyj go
    if _default_client:
        return _default_client.send_text(message)
    
    # Fallback - uzyj settings z config (kompatybilnosc wsteczna)
    try:
        from ..config import settings
        if not settings.PAGE_ACCESS_TOKEN or not settings.RECIPIENT_ID:
            logger.warning("Brak konfiguracji Messenger w settings")
            return False
        
        payload = {
            "recipient": {"id": settings.RECIPIENT_ID},
            "message": {"text": message}
        }
        
        response = requests.post(
            MESSENGER_API_URL,
            headers={
                "Authorization": f"Bearer {settings.PAGE_ACCESS_TOKEN}",
                "Content-Type": "application/json"
            },
            data=json.dumps(payload),
            timeout=DEFAULT_TIMEOUT
        )
        
        if response.status_code == 200:
            logger.debug("Wiadomosc wyslana pomyslnie (via settings)")
            return True
        else:
            logger.error(f"Blad wysylania: {response.status_code} - {response.text}")
            return False
            
    except Exception as e:
        logger.error(f"Blad wysylania wiadomosci: {e}")
        return False


def send_messenger_lines(lines: List[str]) -> bool:
    """
    Wysyla wiele linii przez domyslnego klienta.
    
    Args:
        lines: Lista linii do wyslania
        
    Returns:
        True jesli wyslano pomyslnie
    """
    if not _default_client:
        logger.warning("Klient Messenger nie zainicjalizowany - pomijam wyslanie")
        return False
    
    return _default_client.send_lines(lines)


# Funkcja kompatybilnosci wstecznej dla print_agent
def send_messenger_legacy(
    message: str,
    access_token: str,
    recipient_id: str,
    timeout: int = DEFAULT_TIMEOUT
) -> bool:
    """
    Wysyla wiadomosc z podanymi credentialami (bez globalnego klienta).
    
    Dla kompatybilnosci wstecznej z istniejacym kodem.
    """
    config = MessengerConfig(access_token, recipient_id, timeout)
    client = MessengerClient(config)
    return client.send_text(message)
