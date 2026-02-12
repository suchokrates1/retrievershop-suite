"""
Serwis do monitorowania wyróżnień (promocji) ofert na Allegro.

Funkcjonalności:
- Pobieranie aktywnych wyróżnień
- Sprawdzanie ofert z przedłużeniem następnego dnia
- Wysyłanie alertów o zbliżających się kosztach
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import requests

from ..allegro_api.core import API_BASE_URL, DEFAULT_TIMEOUT
from ..settings_store import settings_store

logger = logging.getLogger(__name__)

PROMO_PACKAGES = {
    'emphasized10d': {'name': 'Wyróżnienie 10-dniowe', 'price': 19.90, 'cycle_days': 10},
    'emphasized1d': {'name': 'Wyróżnienie elastyczne', 'price': 1.99, 'cycle_days': 1},
    'departmentPage': {'name': 'Promowanie na stronie działu', 'price': 19.90, 'cycle_days': 10},
}


@dataclass
class PromoOption:
    """Opcja promowania pojedynczej oferty."""
    offer_id: str
    offer_name: str
    package_id: Optional[str] = None
    package_name: Optional[str] = None
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None
    next_cycle_date: Optional[datetime] = None
    will_renew: bool = False
    estimated_cost: float = 0.0
    
    @property
    def is_active(self) -> bool:
        """Czy wyróżnienie jest aktywne."""
        return self.package_id is not None and self.valid_to is None
    
    @property
    def days_to_renewal(self) -> Optional[int]:
        """Ile dni do przedłużenia (None jeśli nie przedłuży się)."""
        if not self.will_renew or not self.next_cycle_date:
            return None
        now = datetime.now(timezone.utc)
        delta = self.next_cycle_date - now
        return max(0, delta.days)


@dataclass
class PromoSummary:
    """Podsumowanie wyróżnień."""
    active_count: int = 0
    total_estimated_monthly_cost: float = 0.0
    promotions: List[PromoOption] = field(default_factory=list)
    renewing_tomorrow: List[PromoOption] = field(default_factory=list)
    renewing_soon: List[PromoOption] = field(default_factory=list)  # w ciągu 3 dni
    last_check: Optional[datetime] = None
    error: Optional[str] = None


def _parse_datetime(dt_str: Optional[str]) -> Optional[datetime]:
    """Parsuje datę z formatu ISO 8601."""
    if not dt_str:
        return None
    try:
        # Usuń 'Z' i dodaj UTC
        if dt_str.endswith('Z'):
            dt_str = dt_str[:-1] + '+00:00'
        return datetime.fromisoformat(dt_str)
    except (ValueError, TypeError):
        return None


def _get_headers(access_token: str) -> Dict[str, str]:
    """Zwraca nagłówki dla API Allegro."""
    return {
        'Authorization': f'Bearer {access_token}',
        'Accept': 'application/vnd.allegro.public.v1+json',
        'Content-Type': 'application/vnd.allegro.public.v1+json'
    }


def fetch_offer_promo_options(access_token: str, offer_id: str) -> Optional[Dict[str, Any]]:
    """
    Pobiera opcje promowania dla pojedynczej oferty.
    
    Returns:
        Dict z danymi promo-options lub None w przypadku błędu
    """
    url = f'{API_BASE_URL}/sale/offers/{offer_id}/promo-options'
    headers = _get_headers(access_token)
    
    try:
        response = requests.get(url, headers=headers, timeout=DEFAULT_TIMEOUT)
        if response.status_code == 200:
            return response.json()
        else:
            logger.warning(f"Błąd pobierania promo-options dla {offer_id}: {response.status_code}")
            return None
    except requests.RequestException as e:
        logger.error(f"Błąd połączenia przy pobieraniu promo-options: {e}")
        return None


def fetch_all_promo_options(access_token: str, limit: int = 5000) -> List[Dict[str, Any]]:
    """
    Pobiera opcje promowania dla wszystkich ofert sprzedawcy.
    
    Returns:
        Lista słowników z danymi promo-options
    """
    url = f'{API_BASE_URL}/sale/offers/promo-options'
    headers = _get_headers(access_token)
    params = {'limit': limit, 'offset': 0}
    
    all_options = []
    
    try:
        while True:
            response = requests.get(url, headers=headers, params=params, timeout=DEFAULT_TIMEOUT)
            if response.status_code != 200:
                logger.error(f"Błąd pobierania promo-options: {response.status_code} - {response.text[:200]}")
                break
            
            data = response.json()
            options = data.get('promoOptions', [])
            all_options.extend(options)
            
            # Sprawdź czy są kolejne strony
            total = data.get('totalCount', 0)
            if len(all_options) >= total or len(options) == 0:
                break
            
            params['offset'] += limit
            
    except requests.RequestException as e:
        logger.error(f"Błąd połączenia przy pobieraniu promo-options: {e}")
    
    return all_options


def fetch_offer_info(access_token: str, offer_id: str) -> Dict[str, str]:
    """Pobiera nazwe i status publikacji oferty z Allegro API."""
    url = f'{API_BASE_URL}/sale/product-offers/{offer_id}'
    headers = _get_headers(access_token)
    
    try:
        response = requests.get(url, headers=headers, timeout=DEFAULT_TIMEOUT)
        if response.status_code == 200:
            data = response.json()
            return {
                'name': data.get('name', f'Oferta {offer_id}'),
                'publication_status': data.get('publication', {}).get('status', 'UNKNOWN'),
            }
    except requests.RequestException:
        pass
    
    return {'name': f'Oferta {offer_id}', 'publication_status': 'UNKNOWN'}


def fetch_offer_name(access_token: str, offer_id: str) -> str:
    """Pobiera nazwe oferty z Allegro API (kompatybilnosc wsteczna)."""
    return fetch_offer_info(access_token, offer_id)['name']


def get_promotions_summary(access_token: Optional[str] = None) -> PromoSummary:
    """
    Pobiera podsumowanie aktywnych wyróżnień.
    
    Args:
        access_token: Token Allegro (jeśli None, pobierze z settings_store)
        
    Returns:
        PromoSummary z danymi o wyróżnieniach
    """
    if not access_token:
        access_token = settings_store.get('ALLEGRO_ACCESS_TOKEN')
    
    if not access_token:
        return PromoSummary(error="Brak tokenu Allegro")
    
    summary = PromoSummary(last_check=datetime.now(timezone.utc))
    now = datetime.now(timezone.utc)
    tomorrow = now + timedelta(days=1)
    three_days = now + timedelta(days=3)
    
    # Pobierz wszystkie opcje promowania
    all_options = fetch_all_promo_options(access_token)
    
    if not all_options:
        logger.info("Brak aktywnych wyróżnień")
        return summary
    
    # Cache info ofert (pobierane leniwie): offer_id -> {name, publication_status}
    offer_info_cache: Dict[str, Dict[str, str]] = {}
    
    for option in all_options:
        offer_id = option.get('offerId')
        base_package = option.get('basePackage', {})
        
        if not base_package or not base_package.get('id'):
            continue  # Brak aktywnego wyróżnienia
        
        package_id = base_package.get('id')
        package_info = PROMO_PACKAGES.get(package_id, {})
        
        valid_from = _parse_datetime(base_package.get('validFrom'))
        valid_to = _parse_datetime(base_package.get('validTo'))
        next_cycle = _parse_datetime(base_package.get('nextCycleDate'))
        
        # Wyróżnienie jest aktywne jeśli validTo jest None (przedłuża się automatycznie)
        # lub validTo jest w przyszłości
        is_active = valid_to is None or (valid_to and valid_to > now)
        
        if not is_active:
            continue
        
        # Pobierz info o ofercie (leniwie) i odfiltuj zakonczone oferty
        if offer_id not in offer_info_cache:
            offer_info_cache[offer_id] = fetch_offer_info(access_token, offer_id)
        
        offer_info = offer_info_cache[offer_id]
        if offer_info['publication_status'] == 'ENDED':
            logger.debug(
                f"Pomijam wyroznienie dla zakonczonej oferty {offer_id}: "
                f"{offer_info['name'][:50]}"
            )
            continue
        
        # Czy przedłuży się automatycznie
        will_renew = valid_to is None and next_cycle is not None
        
        promo = PromoOption(
            offer_id=offer_id,
            offer_name=offer_info['name'],
            package_id=package_id,
            package_name=package_info.get('name', package_id),
            valid_from=valid_from,
            valid_to=valid_to,
            next_cycle_date=next_cycle,
            will_renew=will_renew,
            estimated_cost=package_info.get('price', 0.0),
        )
        
        summary.promotions.append(promo)
        summary.active_count += 1
        
        # Oblicz szacowany miesięczny koszt
        if will_renew:
            cycle_days = package_info.get('cycle_days', 10)
            cycles_per_month = 30 / cycle_days
            summary.total_estimated_monthly_cost += promo.estimated_cost * cycles_per_month
        
        # Sprawdź czy przedłuża się jutro lub w ciągu 3 dni
        if will_renew and next_cycle:
            if next_cycle.date() == tomorrow.date():
                summary.renewing_tomorrow.append(promo)
            elif next_cycle <= three_days:
                summary.renewing_soon.append(promo)
    
    logger.info(
        f"Znaleziono {summary.active_count} aktywnych wyróżnień, "
        f"{len(summary.renewing_tomorrow)} przedłuża się jutro"
    )
    
    return summary


def disable_promotion(
    access_token: str, 
    offer_id: str, 
    package_id: str = 'emphasized10d',
    immediate: bool = False
) -> bool:
    """
    Wyłącza wyróżnienie dla oferty.
    
    Args:
        access_token: Token Allegro
        offer_id: ID oferty
        package_id: ID pakietu promowania
        immediate: True = wyłącz natychmiast, False = wyłącz z końcem cyklu
        
    Returns:
        True jeśli sukces
    """
    url = f'{API_BASE_URL}/sale/offers/{offer_id}/promo-options-modification'
    headers = _get_headers(access_token)
    
    modification_type = 'REMOVE_NOW' if immediate else 'REMOVE_WITH_END_OF_CYCLE'
    
    body = {
        'modifications': [{
            'modificationType': modification_type,
            'packageType': 'BASE',
            'packageId': package_id
        }]
    }
    
    try:
        response = requests.post(url, headers=headers, json=body, timeout=DEFAULT_TIMEOUT)
        if response.status_code == 200:
            logger.info(f"Wyłączono wyróżnienie dla oferty {offer_id}")
            return True
        else:
            logger.error(f"Błąd wyłączania wyróżnienia: {response.status_code} - {response.text}")
            return False
    except requests.RequestException as e:
        logger.error(f"Błąd połączenia: {e}")
        return False


def format_promotion_alert(summary: PromoSummary) -> Optional[str]:
    """
    Formatuje alert o zbliżających się przedłużeniach wyróżnień.
    
    Returns:
        Tekst alertu lub None jeśli nie ma nic do zgłoszenia
    """
    if not summary.renewing_tomorrow:
        return None
    
    lines = ["Jutro przedluza sie Twoje wyroznienie na:"]
    total_cost = 0.0
    
    for promo in summary.renewing_tomorrow:
        lines.append(f"  - {promo.offer_name[:50]} ({promo.estimated_cost:.2f} zl)")
        total_cost += promo.estimated_cost
    
    lines.append(f"\nLaczny koszt: {total_cost:.2f} zl")
    lines.append("\nWylacz jesli chcesz uniknac kosztow:")
    lines.append("https://magazyn.retrievershop.pl/allegro/promotions")
    
    return "\n".join(lines)


def check_and_notify_promotions(app=None) -> Dict[str, Any]:
    """
    Sprawdza wyróżnienia i wysyła powiadomienia o zbliżających się przedłużeniach.
    
    Ta funkcja jest wywoływana raz dziennie przez scheduler.
    
    Returns:
        Dict ze statusem i informacjami
    """
    from ..notifications.alerts import send_email
    from ..notifications.messenger import send_messenger
    
    result = {
        'checked': False,
        'active_count': 0,
        'renewing_tomorrow': 0,
        'notification_sent': False,
        'error': None
    }
    
    try:
        summary = get_promotions_summary()
        
        if summary.error:
            result['error'] = summary.error
            return result
        
        result['checked'] = True
        result['active_count'] = summary.active_count
        result['renewing_tomorrow'] = len(summary.renewing_tomorrow)
        
        # Wyślij powiadomienie jeśli są oferty przedłużające się jutro
        if summary.renewing_tomorrow:
            alert_text = format_promotion_alert(summary)
            
            if alert_text:
                # Próbuj wysłać przez Messenger
                if send_messenger(alert_text):
                    result['notification_sent'] = True
                    logger.info("Wysłano powiadomienie o wyróżnieniach przez Messenger")
                else:
                    # Fallback na email
                    if send_email("Wyroznienia Allegro - przedluzenie jutro", alert_text):
                        result['notification_sent'] = True
                        logger.info("Wysłano powiadomienie o wyróżnieniach przez email")
        
        logger.info(f"Sprawdzanie wyróżnień zakończone: {result}")
        
    except Exception as e:
        logger.error(f"Błąd sprawdzania wyróżnień: {e}", exc_info=True)
        result['error'] = str(e)
    
    return result
