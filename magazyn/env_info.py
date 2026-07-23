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
    "WFIRMA_ACCESS_KEY": (
        "Klucz dostepu wFirma",
        "Klucz API do integracji z wFirma (fakturowanie)",
    ),
    "WFIRMA_SECRET_KEY": (
        "Klucz tajny wFirma",
        "Sekretny klucz API wFirma",
    ),
    "WFIRMA_APP_KEY": (
        "Klucz aplikacji wFirma",
        "Identyfikator aplikacji w wFirma API",
    ),
    "WFIRMA_COMPANY_ID": (
        "ID firmy wFirma",
        "Identyfikator firmy w systemie wFirma",
    ),
    "ALLEGRO_AUTORESPONDER_ENABLED": (
        "Autoresponder Allegro",
        "Wlacz automatyczne odpowiedzi na wiadomosci Allegro (1 = wlaczony)",
    ),
    "ALLEGRO_AUTORESPONDER_MESSAGE": (
        "Tresc autorespondera",
        "Tresc automatycznej odpowiedzi wysylanej do kupujacych",
    ),
    "WOO_URL": (
        "URL sklepu WooCommerce",
        "Np. https://retrievershop.pl/",
    ),
    "WOO_CONSUMER_KEY": (
        "WooCommerce Consumer Key",
        "Klucz REST API (ck_...)",
    ),
    "WOO_CONSUMER_SECRET": (
        "WooCommerce Consumer Secret",
        "Sekret REST API (cs_...)",
    ),
    "WOO_WEBHOOK_SECRET": (
        "WooCommerce Webhook Secret",
        "Secret do weryfikacji podpisu X-WC-Webhook-Signature",
    ),
    "WOO_FEE_CARD_PCT": (
        "WooPayments karta (%)",
        "Fallback prowizji karty / Apple Pay / Google Pay (domyslnie 1.50)",
    ),
    "WOO_FEE_CARD_FIXED": (
        "WooPayments karta (zl)",
        "Stala oplata karty (domyslnie 1.00 zl)",
    ),
    "WOO_FEE_P24_PCT": (
        "WooPayments P24 (%)",
        "Fallback prowizji Przelewy24 (domyslnie 1.90)",
    ),
    "WOO_FEE_P24_FIXED": (
        "WooPayments P24 (zl)",
        "Stala oplata P24 (domyslnie 1.00 zl)",
    ),
    "NEWSLETTER_MAIL_SECRET": (
        "Newsletter Mail Secret",
        "Bearer/HMAC secret dla WP → magazyn (welcome z kuponem). Puste = WOO_WEBHOOK_SECRET",
    ),
    "WP_APP_USER": (
        "WordPress Application User",
        "Login admina WP do uploadu mediow (np. retrievershop)",
    ),
    "WP_APP_PASSWORD": (
        "WordPress Application Password",
        "Haslo aplikacji WP (Uzytkownicy → Profil → Hasla aplikacji)",
    ),
    "INPOST_TOKEN": (
        "InPost ShipX Token",
        "Bearer token API ShipX (etykiety Woo)",
    ),
    "INPOST_ORGANIZATION_ID": (
        "InPost Organization ID",
        "ID organizacji w panelu InPost / ShipX",
    ),
    "INPOST_SENDING_METHOD": (
        "InPost sending_method",
        "Sposob nadania C2C: parcel_locker lub dispatch_order",
    ),
    "INPOST_SHOP_LOCKER_A": (
        "InPost sklep paczkomat A (zl)",
        "Koszt sprzedawcy paczkomat gabaryt A (fallback, domyslnie 16.49)",
    ),
    "INPOST_SHOP_LOCKER_B": (
        "InPost sklep paczkomat B (zl)",
        "Koszt sprzedawcy paczkomat gabaryt B (fallback, domyslnie 18.49)",
    ),
    "INPOST_SHOP_LOCKER_C": (
        "InPost sklep paczkomat C (zl)",
        "Koszt sprzedawcy paczkomat gabaryt C (fallback, domyslnie 20.49)",
    ),
    "INPOST_SHOP_COURIER_A": (
        "InPost sklep kurier A (zl)",
        "Koszt sprzedawcy kurier gabaryt A (fallback, domyslnie 19.49)",
    ),
    "INPOST_SHOP_COURIER_B": (
        "InPost sklep kurier B (zl)",
        "Koszt sprzedawcy kurier gabaryt B (fallback, domyslnie 20.49)",
    ),
    "INPOST_SHOP_COURIER_C": (
        "InPost sklep kurier C (zl)",
        "Koszt sprzedawcy kurier gabaryt C (fallback, domyslnie 25.49)",
    ),
    "INPOST_RETURNS_CLIENT_ID": (
        "InPost Returns client_id",
        "OAuth client_id do Returns REST API (nie ShipX) — customer-paid zwroty",
    ),
    "INPOST_RETURNS_CLIENT_SECRET": (
        "InPost Returns client_secret",
        "OAuth client_secret do Returns REST API",
    ),
}
