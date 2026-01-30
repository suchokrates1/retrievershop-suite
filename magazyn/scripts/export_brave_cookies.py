#!/usr/bin/env python3
"""
Eksport cookies z przegladarki Brave/Chrome dla Allegro.

Cookies w Chromium sa zaszyfrowane kluczem DPAPI (Windows).
Ten skrypt odszyfrowuje je i eksportuje do formatu JSON.

Wymagania:
    pip install pycryptodome pywin32

Uzycie:
    python export_brave_cookies.py
    python export_brave_cookies.py --browser chrome
    python export_brave_cookies.py --output allegro_cookies.json
"""

import os
import sys
import json
import shutil
import sqlite3
import base64
import argparse
from pathlib import Path
from datetime import datetime, timedelta

# Sciezki do przegladarek na Windows
BROWSER_PATHS = {
    "brave": Path(os.environ.get("LOCALAPPDATA", "")) / "BraveSoftware" / "Brave-Browser" / "User Data",
    "chrome": Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "User Data",
    "edge": Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Edge" / "User Data",
}


def get_encryption_key(browser: str) -> bytes:
    """Pobiera klucz szyfrowania z Local State."""
    try:
        import win32crypt
        from Crypto.Cipher import AES
    except ImportError:
        print("Wymagane pakiety: pip install pycryptodome pywin32")
        sys.exit(1)
    
    local_state_path = BROWSER_PATHS[browser] / "Local State"
    
    if not local_state_path.exists():
        raise FileNotFoundError(f"Nie znaleziono: {local_state_path}")
    
    with open(local_state_path, "r", encoding="utf-8") as f:
        local_state = json.load(f)
    
    # Klucz jest zakodowany w base64 z prefiksem "DPAPI"
    encrypted_key = base64.b64decode(local_state["os_crypt"]["encrypted_key"])
    
    # Usun prefix "DPAPI" (5 bajtow)
    encrypted_key = encrypted_key[5:]
    
    # Odszyfruj klucz uzywajac Windows DPAPI
    decrypted_key = win32crypt.CryptUnprotectData(encrypted_key, None, None, None, 0)[1]
    
    return decrypted_key


def decrypt_cookie_value(encrypted_value: bytes, key: bytes) -> str:
    """Odszyfrowuje wartosc cookie."""
    try:
        from Crypto.Cipher import AES
    except ImportError:
        return ""
    
    if not encrypted_value:
        return ""
    
    # Nowy format v10/v20 (AES-GCM)
    if encrypted_value[:3] == b"v10" or encrypted_value[:3] == b"v20":
        # Nonce to 12 bajtow po prefiksie
        nonce = encrypted_value[3:15]
        ciphertext = encrypted_value[15:]
        
        try:
            cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
            decrypted = cipher.decrypt_and_verify(ciphertext[:-16], ciphertext[-16:])
            return decrypted.decode("utf-8")
        except Exception as e:
            print(f"Blad deszyfrowania: {e}")
            return ""
    
    # Stary format (DPAPI)
    try:
        import win32crypt
        decrypted = win32crypt.CryptUnprotectData(encrypted_value, None, None, None, 0)[1]
        return decrypted.decode("utf-8")
    except Exception:
        return ""


def chrome_timestamp_to_datetime(timestamp: int) -> datetime:
    """Konwertuje timestamp Chrome na datetime."""
    # Chrome timestamp: mikrosekundy od 1601-01-01
    if timestamp == 0:
        return datetime.now() + timedelta(days=365)
    
    epoch_start = datetime(1601, 1, 1)
    return epoch_start + timedelta(microseconds=timestamp)


def export_allegro_cookies(browser: str = "brave", output_file: str = "allegro_cookies.json") -> list:
    """Eksportuje cookies Allegro z przegladarki."""
    
    if browser not in BROWSER_PATHS:
        raise ValueError(f"Nieobslugiwana przegladarka: {browser}")
    
    # Sciezka do cookies
    cookies_path = BROWSER_PATHS[browser] / "Default" / "Network" / "Cookies"
    
    if not cookies_path.exists():
        # Probuj stara lokalizacje
        cookies_path = BROWSER_PATHS[browser] / "Default" / "Cookies"
    
    if not cookies_path.exists():
        raise FileNotFoundError(f"Nie znaleziono cookies: {cookies_path}")
    
    print(f"Odczytuje cookies z: {cookies_path}")
    
    # Skopiuj plik cookies (bo moze byc zablokowany przez przegladarke)
    temp_cookies = Path("temp_cookies.db")
    shutil.copy2(cookies_path, temp_cookies)
    
    try:
        # Pobierz klucz szyfrowania
        key = get_encryption_key(browser)
        print("Klucz szyfrowania pobrany")
        
        # Polacz z baza
        conn = sqlite3.connect(temp_cookies)
        cursor = conn.cursor()
        
        # Pobierz cookies dla allegro.pl
        cursor.execute("""
            SELECT host_key, name, encrypted_value, path, expires_utc, is_secure, is_httponly, samesite
            FROM cookies
            WHERE host_key LIKE '%allegro%'
        """)
        
        cookies = []
        for row in cursor.fetchall():
            host_key, name, encrypted_value, path, expires_utc, is_secure, is_httponly, samesite = row
            
            value = decrypt_cookie_value(encrypted_value, key)
            
            if not value:
                continue
            
            # Konwertuj samesite
            samesite_map = {0: "None", 1: "Lax", 2: "Strict", -1: "Lax"}
            samesite_str = samesite_map.get(samesite, "Lax")
            
            cookie = {
                "name": name,
                "value": value,
                "domain": host_key,
                "path": path,
                "secure": bool(is_secure),
                "httpOnly": bool(is_httponly),
                "sameSite": samesite_str,
            }
            
            # Dodaj expiry jesli nie jest sesyjne
            if expires_utc > 0:
                expiry_dt = chrome_timestamp_to_datetime(expires_utc)
                cookie["expiry"] = int(expiry_dt.timestamp())
            
            cookies.append(cookie)
            print(f"  Cookie: {name} = {value[:30]}..." if len(value) > 30 else f"  Cookie: {name} = {value}")
        
        conn.close()
        
        print(f"\nZnaleziono {len(cookies)} cookies dla Allegro")
        
        # Zapisz do pliku
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(cookies, f, indent=2, ensure_ascii=False)
        
        print(f"Zapisano do: {output_file}")
        
        return cookies
        
    finally:
        # Usun tymczasowy plik
        if temp_cookies.exists():
            temp_cookies.unlink()


def main():
    parser = argparse.ArgumentParser(description="Eksport cookies Allegro z przegladarki")
    parser.add_argument("--browser", "-b", choices=["brave", "chrome", "edge"], default="brave",
                        help="Przegladarka zrodlowa (domyslnie: brave)")
    parser.add_argument("--output", "-o", default="allegro_cookies.json",
                        help="Plik wyjsciowy (domyslnie: allegro_cookies.json)")
    
    args = parser.parse_args()
    
    try:
        cookies = export_allegro_cookies(args.browser, args.output)
        
        if not cookies:
            print("\nBrak cookies Allegro! Upewnij sie, ze jestes zalogowany w przegladarce.")
            sys.exit(1)
        
        # Sprawdz czy sa wazne cookies sesji
        important_cookies = {"gdpr_permission_given", "allegro.login", "wdctx"}
        found = {c["name"] for c in cookies}
        
        print("\nWazne cookies:")
        for name in important_cookies:
            status = "OK" if name in found else "BRAK"
            print(f"  {name}: {status}")
        
    except FileNotFoundError as e:
        print(f"Blad: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Blad: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
