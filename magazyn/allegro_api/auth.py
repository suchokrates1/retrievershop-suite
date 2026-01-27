"""
Autoryzacja OAuth dla Allegro API.
"""
from typing import Optional

import requests

from .core import AUTH_URL, DEFAULT_TIMEOUT
from ..settings_store import SettingsPersistenceError, settings_store


def get_access_token(
    client_id: str, 
    client_secret: str, 
    code: str, 
    redirect_uri: Optional[str] = None
) -> dict:
    """
    Uzyskaj access token i refresh token z Allegro.

    Parameters
    ----------
    client_id : str
        Identyfikator aplikacji Allegro.
    client_secret : str
        Klucz tajny aplikacji Allegro.
    code : str
        Kod autoryzacyjny uzyskany po zgodzie użytkownika.
    redirect_uri : Optional[str]
        URI przekierowania użyty podczas autoryzacji.

    Returns
    -------
    dict
        Odpowiedź JSON zawierająca tokeny i dane wygaśnięcia.
    """
    data = {"grant_type": "authorization_code", "code": code}
    if redirect_uri:
        data["redirect_uri"] = redirect_uri

    response = requests.post(
        AUTH_URL, data=data, auth=(client_id, client_secret), timeout=DEFAULT_TIMEOUT
    )
    response.raise_for_status()
    return response.json()


def refresh_token(refresh_token: str) -> dict:
    """
    Odśwież access token używając danych z settings_store.

    Zarówno identyfikator klienta jak i sekret muszą być zapisane
    w settings store. Jeśli brakuje którejkolwiek wartości,
    zostanie wyrzucony ValueError.
    """

    def _normalize(value: Optional[str]) -> Optional[str]:
        return value or None

    try:
        store_client_id = _normalize(settings_store.get("ALLEGRO_CLIENT_ID"))
        store_client_secret = _normalize(settings_store.get("ALLEGRO_CLIENT_SECRET"))
    except SettingsPersistenceError as exc:
        raise ValueError(
            "Brak danych uwierzytelniających Allegro. Nie można odczytać ustawień."
        ) from exc

    if not (store_client_id and store_client_secret):
        raise ValueError(
            "Brak danych uwierzytelniających Allegro. Uzupełnij ALLEGRO_CLIENT_ID i "
            "ALLEGRO_CLIENT_SECRET w ustawieniach."
        )

    data = {"grant_type": "refresh_token", "refresh_token": refresh_token}
    response = requests.post(
        AUTH_URL,
        data=data,
        auth=(store_client_id, store_client_secret),
        timeout=DEFAULT_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()
