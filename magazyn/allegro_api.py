import os
from typing import Optional

import requests

AUTH_URL = "https://allegro.pl/auth/oauth/token"
API_BASE_URL = "https://api.allegro.pl"


def get_access_token(client_id: str, client_secret: str, code: str, redirect_uri: Optional[str] = None) -> dict:
    """Obtain an access token and refresh token from Allegro.

    Parameters
    ----------
    client_id : str
        Identifier of the Allegro application.
    client_secret : str
        Secret key for the Allegro application.
    code : str
        Authorization code obtained after user consent.
    redirect_uri : Optional[str]
        Redirect URI used during the authorization request.

    Returns
    -------
    dict
        JSON response containing tokens and expiration data.
    """
    data = {"grant_type": "authorization_code", "code": code}
    if redirect_uri:
        data["redirect_uri"] = redirect_uri

    response = requests.post(AUTH_URL, data=data, auth=(client_id, client_secret))
    response.raise_for_status()
    return response.json()


def refresh_token(refresh_token: str) -> dict:
    """Refresh the access token using a refresh token.

    The client identifier and secret can be provided via the environment
    variables ``ALLEGRO_CLIENT_ID`` and ``ALLEGRO_CLIENT_SECRET``.
    """
    client_id = os.getenv("ALLEGRO_CLIENT_ID")
    client_secret = os.getenv("ALLEGRO_CLIENT_SECRET")
    auth = (client_id, client_secret) if client_id and client_secret else None

    data = {"grant_type": "refresh_token", "refresh_token": refresh_token}
    response = requests.post(AUTH_URL, data=data, auth=auth)
    response.raise_for_status()
    return response.json()


def fetch_offers(access_token: str, page: int = 1) -> dict:
    """Fetch offers from Allegro using a valid access token.

    Parameters
    ----------
    access_token : str
        OAuth access token for Allegro API.
    page : int
        Page number of results to retrieve. Defaults to ``1``.

    Returns
    -------
    dict
        JSON response with the list of offers.
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.allegro.public.v1+json",
    }
    params = {"page": page}
    url = f"{API_BASE_URL}/sale/offers"

    response = requests.get(url, headers=headers, params=params)
    response.raise_for_status()
    return response.json()
