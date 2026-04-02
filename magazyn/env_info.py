ENV_INFO = {
    "PAGE_ACCESS_TOKEN": (
        "Token Dostępu Strony",
        "Token strony w Messengerze do wysyłania powiadomień",
    ),
    "RECIPIENT_ID": (
        "ID odbiorcy",
        "Identyfikator w Messengerze, który otrzymuje powiadomienia",
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
    "COMMISSION_ALLEGRO": (
        "Prowizja Allegro (%)",
        "Procent prowizji pobieranej przez Allegro",
    ),
    "LOW_STOCK_THRESHOLD": (
        "Próg niskiego stanu",
        "Ilość przy której wysyłane jest powiadomienie",
    ),
    "ALERT_EMAIL": (
        "Email alertów",
        "Adres email do powiadomień o niskim stanie",
    ),
    "SMTP_SERVER": ("Serwer SMTP", "Adres serwera SMTP do wysyłki e-mail"),
    "SMTP_PORT": ("Port SMTP", "Port serwera SMTP"),
    "SMTP_USERNAME": ("Użytkownik SMTP", "Login do serwera SMTP"),
    "SMTP_PASSWORD": ("Haslo SMTP", "Haslo do serwera SMTP"),
    "EMAIL_FROM_NAME": (
        "Nazwa nadawcy email",
        "Nazwa wyswietlana jako nadawca maili do klientow (domyslnie: Retriever Shop)",
    ),
    "APP_BASE_URL": (
        "Bazowy URL aplikacji",
        "Publiczny adres aplikacji do linkow w mailach, np. https://magazyn.retrievershop.pl",
    ),
    "ENABLE_WEEKLY_REPORTS": (
        "Raport tygodniowy",
        "Wysyłaj raport tygodniowy",
    ),
    "ENABLE_MONTHLY_REPORTS": (
        "Raport miesięczny",
        "Wysyłaj raport miesięczny",
    ),
    "PACKAGING_COST": (
        "Cena pakowania",
        "Koszt pakowania jednego zamowienia (PLN)",
    ),
    "SENDER_NAME": (
        "Nazwa nadawcy przesylki",
        "Nazwa osoby na etykiecie nadawczej",
    ),
    "SENDER_COMPANY": (
        "Nazwa firmy nadawcy",
        "Nazwa firmy na etykiecie nadawczej (pole company)",
    ),
    "SENDER_STREET": (
        "Ulica nadawcy",
        "Adres ulicy nadawcy na etykiecie",
    ),
    "SENDER_CITY": (
        "Miasto nadawcy",
        "Miasto nadawcy na etykiecie",
    ),
    "SENDER_ZIPCODE": (
        "Kod pocztowy nadawcy",
        "Kod pocztowy nadawcy na etykiecie",
    ),
    "SENDER_EMAIL": (
        "Email nadawcy",
        "Adres email nadawcy na etykiecie",
    ),
    "SENDER_PHONE": (
        "Telefon nadawcy",
        "Numer telefonu nadawcy na etykiecie",
    ),
    "PRICE_MAX_DISCOUNT_PERCENT": (
        "Max znizka dla sugestii cen (%)",
        "Maksymalny procent obnizki przy ktorym pokazywane sa sugestie cen w raportach (domyslnie 5%)",
    ),
}
