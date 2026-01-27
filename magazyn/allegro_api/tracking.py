"""
Sledzenie przesylek Allegro API.
"""
import requests

from .core import API_BASE_URL, _request_with_retry


def fetch_parcel_tracking(access_token: str, carrier_id: str, waybills: list[str]) -> dict:
    """
    Pobierz historię śledzenia przesyłek dla podanych numerów listów przewozowych.
    
    Endpoint: GET /order/carriers/{carrierId}/tracking
    
    Args:
        access_token: Token dostępu Allegro OAuth
        carrier_id: Identyfikator przewoźnika (np. "ALLEGRO", "INPOST", "DPD", "POCZTA_POLSKA")
        waybills: Lista numerów listów przewozowych (max 20)
    
    Returns:
        dict: Historia statusów przesyłek, format:
        {
            "carrierId": "ALLEGRO",
            "waybills": [
                {
                    "waybill": "123456789",
                    "events": [
                        {
                            "occurredAt": "2024-01-15T10:30:00Z",
                            "type": "DELIVERED",
                            "description": "Przesyłka dostarczona"
                        }
                    ]
                }
            ]
        }
    
    Raises:
        ValueError: Jeśli podano więcej niż 20 numerów przesyłek
        HTTPError: Jeśli żądanie API nie powiodło się
    
    Example:
        >>> tracking = fetch_parcel_tracking(token, "INPOST", ["123456789012"])
        >>> for waybill_data in tracking["waybills"]:
        ...     print(f"Waybill: {waybill_data['waybill']}")
        ...     for event in waybill_data["events"]:
        ...         print(f"  {event['occurredAt']}: {event['type']}")
    """
    if len(waybills) > 20:
        raise ValueError("Maksymalnie 20 numerów przesyłek na jedno żądanie")
    
    if not waybills:
        return {"carrierId": carrier_id, "waybills": []}
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.allegro.public.v1+json",
    }
    
    params = [("waybill", wb) for wb in waybills]
    
    url = f"{API_BASE_URL}/order/carriers/{carrier_id}/tracking"
    
    response = _request_with_retry(
        requests.get,
        url,
        endpoint="parcel_tracking",
        headers=headers,
        params=params,
    )
    
    return response.json()
