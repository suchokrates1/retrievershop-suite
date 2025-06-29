ENV_INFO = {
    "API_TOKEN": ("Token API", "Klucz API BaseLinker do pobierania zamówień"),
    "PAGE_ACCESS_TOKEN": (
        "Token Dostępu Strony",
        "Token strony w Messengerze do wysyłania powiadomień",
    ),
    "RECIPIENT_ID": (
        "ID odbiorcy",
        "Identyfikator w Messengerze, który otrzymuje powiadomienia",
    ),
    "STATUS_ID": (
        "ID statusu",
        "ID statusu zamówienia filtrowanych do wydruku",
    ),
    "PRINTER_NAME": ("Nazwa drukarki", "Nazwa używanej drukarki CUPS"),
    "CUPS_SERVER": ("Serwer CUPS", "Nazwa hosta zdalnego serwera CUPS"),
    "CUPS_PORT": ("Port CUPS", "Port zdalnego serwera CUPS"),
    "POLL_INTERVAL": (
        "Interwał sprawdzania",
        "Liczba sekund między sprawdzeniami zamówień",
    ),
    "QUIET_HOURS_START": (
        "Początek ciszy nocnej",
        "Godzina rozpoczęcia wyciszenia wydruków (format 24h)",
    ),
    "QUIET_HOURS_END": (
        "Koniec ciszy nocnej",
        "Godzina zakończenia wyciszenia wydruków (format 24h)",
    ),
    "TIMEZONE": (
        "Strefa czasowa",
        "Strefa czasowa IANA używana do sprawdzania ciszy nocnej",
    ),
    "PRINTED_EXPIRY_DAYS": (
        "Dni przechowywania wydruków",
        "Liczba dni przechowywania ID wydrukowanych zamówień w bazie",
    ),
    "LOG_LEVEL": ("Poziom logów", "Poziom logowania agenta drukującego"),
    "LOG_FILE": ("Plik logu", "Ścieżka do pliku logu agenta"),
    "SECRET_KEY": ("Tajny klucz", "Tajny klucz sesji Flask"),
    "FLASK_DEBUG": (
        "Debug Flask",
        "Ustaw 1 aby włączyć tryb debugowania Flask",
    ),
    "FLASK_ENV": ("Środowisko Flask", "Konfiguracja środowiska Flask"),
    "DEFAULT_SHIPPING_ALLEGRO": (
        "Wysyłka Allegro",
        "Domyślny koszt wysyłki dla platformy Allegro",
    ),
    "DEFAULT_SHIPPING_VINTED": (
        "Wysyłka Vinted",
        "Domyślny koszt wysyłki dla platformy Vinted",
    ),
    "COMMISSION_ALLEGRO": (
        "Prowizja Allegro (%)",
        "Procent prowizji pobieranej przez Allegro",
    ),
    "COMMISSION_VINTED": (
        "Prowizja Vinted (%)",
        "Procent prowizji pobieranej przez Vinted",
    ),
}
