"""
Klient HTTP wFirma API.

Autoryzacja: API Key (accessKey, secretKey, appKey)
URL bazowe: https://api2.wfirma.pl
Format: JSON (inputFormat=json&outputFormat=json)

Dokumentacja: https://doc.wfirma.pl/
"""
import logging
import time
from typing import Optional

import requests
from requests.exceptions import RequestException

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 15
MAX_RETRY_ATTEMPTS = 3
RETRY_BACKOFF = 2.0
MAX_BACKOFF = 30.0


class WFirmaError(Exception):
    """Blad API wFirma."""

    def __init__(self, message: str, code: Optional[str] = None, details: Optional[dict] = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


class WFirmaClient:
    """Klient HTTP dla wFirma API v2."""

    BASE_URL = "https://api2.wfirma.pl"

    def __init__(
        self,
        access_key: str,
        secret_key: str,
        app_key: Optional[str] = None,
        company_id: Optional[str] = None,
    ):
        if not access_key or not secret_key:
            raise ValueError("wFirma: wymagane access_key i secret_key")

        self._headers = {
            "accessKey": access_key,
            "secretKey": secret_key,
            "Content-Type": "application/json",
        }
        if app_key:
            self._headers["appKey"] = app_key

        self.company_id = company_id

    @classmethod
    def from_settings(cls) -> "WFirmaClient":
        """Utworz klienta z ustawien settings_store."""
        from ..settings_store import settings_store

        access_key = settings_store.get("WFIRMA_ACCESS_KEY")
        secret_key = settings_store.get("WFIRMA_SECRET_KEY")
        app_key = settings_store.get("WFIRMA_APP_KEY")
        company_id = settings_store.get("WFIRMA_COMPANY_ID")

        if not access_key or not secret_key:
            raise WFirmaError(
                "Brak kluczy wFirma w ustawieniach "
                "(WFIRMA_ACCESS_KEY, WFIRMA_SECRET_KEY)"
            )

        return cls(
            access_key=access_key,
            secret_key=secret_key,
            app_key=app_key,
            company_id=company_id,
        )

    def request(self, action: str, data: Optional[dict] = None, method: str = "POST") -> dict:
        """
        Wykonaj zadanie do wFirma API z retry logic.

        Parameters
        ----------
        action : str
            Sciezka API, np. 'invoices/add', 'contractors/find'.
        data : dict, optional
            Dane JSON do wyslania.
        method : str
            Metoda HTTP (POST, GET, PUT, DELETE). Domyslnie POST.

        Returns
        -------
        dict
            Odpowiedz JSON z wFirma.

        Raises
        ------
        WFirmaError
            Gdy API zwroci blad lub request nie powiedzie sie.
        """
        url = f"{self.BASE_URL}/{action}"
        params = {"inputFormat": "json", "outputFormat": "json"}
        if self.company_id:
            params["company_id"] = self.company_id

        attempt = 0
        backoff = RETRY_BACKOFF

        while True:
            attempt += 1
            try:
                if method.upper() == "GET":
                    response = requests.get(
                        url,
                        headers=self._headers,
                        params=params,
                        timeout=DEFAULT_TIMEOUT,
                    )
                else:
                    response = requests.post(
                        url,
                        headers=self._headers,
                        params=params,
                        json=data,
                        timeout=DEFAULT_TIMEOUT,
                    )
            except RequestException as exc:
                if attempt >= MAX_RETRY_ATTEMPTS:
                    raise WFirmaError(f"Blad polaczenia z wFirma: {exc}") from exc
                logger.warning(
                    "wFirma request %s/%s nieudany: %s, ponawiam za %.1fs",
                    attempt, MAX_RETRY_ATTEMPTS, exc, backoff,
                )
                time.sleep(backoff)
                backoff = min(backoff * 2, MAX_BACKOFF)
                continue

            # Sprawdz HTTP status
            if response.status_code >= 500:
                if attempt < MAX_RETRY_ATTEMPTS:
                    logger.warning(
                        "wFirma HTTP %d, ponawiam za %.1fs",
                        response.status_code, backoff,
                    )
                    time.sleep(backoff)
                    backoff = min(backoff * 2, MAX_BACKOFF)
                    continue

            if response.status_code == 429:
                if attempt < MAX_RETRY_ATTEMPTS:
                    retry_after = float(response.headers.get("Retry-After", backoff))
                    logger.warning("wFirma rate limit, czekam %.1fs", retry_after)
                    time.sleep(retry_after)
                    backoff = min(backoff * 2, MAX_BACKOFF)
                    continue

            # Parsuj odpowiedz
            try:
                result = response.json()
            except ValueError:
                raise WFirmaError(
                    f"wFirma zwrocil nieprawidlowy JSON (HTTP {response.status_code})",
                    details={"body": response.text[:500]},
                )

            # Sprawdz bledy w odpowiedzi
            status = result.get("status", {})
            if isinstance(status, dict) and status.get("code") == "ERROR":
                error_msg = status.get("message") or ""
                # Wyciagnij szczegoly walidacji z odpowiedzi
                if not error_msg:
                    for key, entries in result.items():
                        if key == "status" or not isinstance(entries, list):
                            continue
                        for entry in entries:
                            if not isinstance(entry, dict):
                                continue
                            for obj in entry.values():
                                if isinstance(obj, dict) and "errors" in obj:
                                    for err in obj["errors"]:
                                        if isinstance(err, dict):
                                            for field_errors in err.values():
                                                if isinstance(field_errors, list):
                                                    error_msg = "; ".join(field_errors)
                if not error_msg:
                    error_msg = "Nieznany blad wFirma"
                raise WFirmaError(
                    error_msg,
                    code=status.get("code"),
                    details=result,
                )

            if response.status_code >= 400:
                raise WFirmaError(
                    f"wFirma HTTP {response.status_code}",
                    details=result,
                )

            return result

    def download(self, action: str) -> bytes:
        """
        Pobierz plik binarny z wFirma (np. PDF faktury).

        Parameters
        ----------
        action : str
            Sciezka API, np. 'invoices/download/12345'.

        Returns
        -------
        bytes
            Zawartosc pliku.
        """
        url = f"{self.BASE_URL}/{action}"
        params = {}
        if self.company_id:
            params["company_id"] = self.company_id

        try:
            response = requests.get(
                url,
                headers=self._headers,
                params=params,
                timeout=DEFAULT_TIMEOUT * 2,
            )
            response.raise_for_status()
        except RequestException as exc:
            raise WFirmaError(f"Blad pobierania pliku z wFirma: {exc}") from exc

        return response.content
