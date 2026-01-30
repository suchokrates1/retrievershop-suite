#!/usr/bin/env python3
"""
Eksport cookies z przegladarki Brave/Chrome dla Allegro.

Uzywa biblioteki browser_cookie3 ktora obsluguje rozne formaty szyfrowania.

Wymagania:
    pip install browser_cookie3

Uzycie:
    python export_cookies_simple.py
    python export_cookies_simple.py --browser chrome
"""

import json
import argparse

try:
    import browser_cookie3
except ImportError:
    print("Zainstaluj: pip install browser_cookie3")
    exit(1)


def export_allegro_cookies(browser: str = "brave", output_file: str = "allegro_cookies.json") -> list:
    """Eksportuje cookies Allegro z przegladarki."""
    
    print(f"Odczytuje cookies z przegladarki: {browser}")
    
    # Pobierz cookiejar
    if browser == "brave":
        cj = browser_cookie3.brave(domain_name=".allegro.pl")
    elif browser == "chrome":
        cj = browser_cookie3.chrome(domain_name=".allegro.pl")
    elif browser == "edge":
        cj = browser_cookie3.edge(domain_name=".allegro.pl")
    elif browser == "firefox":
        cj = browser_cookie3.firefox(domain_name=".allegro.pl")
    else:
        raise ValueError(f"Nieobslugiwana przegladarka: {browser}")
    
    cookies = []
    for cookie in cj:
        c = {
            "name": cookie.name,
            "value": cookie.value,
            "domain": cookie.domain,
            "path": cookie.path,
            "secure": cookie.secure,
            "httpOnly": bool(cookie.has_nonstandard_attr("HttpOnly")),
        }
        
        if cookie.expires:
            c["expiry"] = cookie.expires
        
        cookies.append(c)
        
        # Wyswietl (ukryj dlugie wartosci)
        val_display = cookie.value[:40] + "..." if len(cookie.value) > 40 else cookie.value
        print(f"  {cookie.name}: {val_display}")
    
    print(f"\nZnaleziono {len(cookies)} cookies dla Allegro")
    
    # Zapisz do pliku
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(cookies, f, indent=2, ensure_ascii=False)
    
    print(f"Zapisano do: {output_file}")
    
    return cookies


def main():
    parser = argparse.ArgumentParser(description="Eksport cookies Allegro z przegladarki")
    parser.add_argument("--browser", "-b", choices=["brave", "chrome", "edge", "firefox"], 
                        default="brave", help="Przegladarka (domyslnie: brave)")
    parser.add_argument("--output", "-o", default="allegro_cookies.json",
                        help="Plik wyjsciowy (domyslnie: allegro_cookies.json)")
    
    args = parser.parse_args()
    
    try:
        cookies = export_allegro_cookies(args.browser, args.output)
        
        if not cookies:
            print("\nBrak cookies Allegro! Upewnij sie, ze jestes zalogowany.")
            exit(1)
        
        # Sprawdz wazne cookies
        important = {"gdpr_permission_given", "wdctx", "datadome"}
        found = {c["name"] for c in cookies}
        
        print("\nStatus waznych cookies:")
        for name in important:
            if name in found:
                print(f"  {name}: OK")
            else:
                print(f"  {name}: BRAK")
                
    except Exception as e:
        print(f"Blad: {e}")
        import traceback
        traceback.print_exc()
        exit(1)


if __name__ == "__main__":
    main()
