"""
Jedyne zrodlo prawdy dla statusow zamowien.

Wszystkie moduly importuja stale statusow stad.
Nie definiuj mapowania statusow nigdzie indziej.
"""

# ── Nowy flow statusow ─────────────────────────────────────────────
#
# pobrano(0) → wydrukowano(2) → spakowano(3) → wyslano(4)
#   → w_transporcie(5) → w_punkcie(6) → dostarczono(7)
#
# Problemy (999): blad_druku, problem_z_dostawa, zwrot, anulowano
# ────────────────────────────────────────────────────────────────────

VALID_STATUSES = [
    # Etap wewnetrzny (magazyn)
    "pobrano",           # Pobrano zamowienie z Allegro
    "wydrukowano",       # Etykieta wydrukowana
    "spakowano",         # Zeskanowano etykiete + EAN produktow

    # Etap transportu
    "wyslano",           # Kurier potwierdzil odbior (COLLECTED/IN_TRANSIT)
    "w_transporcie",     # Ostatnia mila (OUT_FOR_DELIVERY)
    "w_punkcie",         # W punkcie odbioru / gotowe do odbioru

    # Final
    "dostarczono",       # Doreczono klientowi

    # Problemy (mogą byc ustawione z dowolnego stanu)
    "blad_druku",        # Blad tworzenia/drukowania etykiety
    "problem_z_dostawa", # Niedostarczono / zagubiono / blad dostawy
    "zwrot",             # Zwrot od klienta
    "anulowano",         # Anulowano
]

STATUS_HIERARCHY = {
    "pobrano": 0,
    "wydrukowano": 2,
    "spakowano": 3,
    "wyslano": 4,
    "w_transporcie": 5,
    "w_punkcie": 6,
    "dostarczono": 7,
    # Problemy — mozna ustawic z dowolnego stanu
    "blad_druku": 999,
    "problem_z_dostawa": 999,
    "zwrot": 999,
    "anulowano": 999,
}


# ── Allegro Parcel Tracking API events → status wewnetrzny ─────────
# https://developer.allegro.pl/documentation/#operation/getParcelTrackingUsingGET

ALLEGRO_TRACKING_MAP = {
    # Ignorowane — rejestracja trackingu, kurier jeszcze nie odebral
    "CREATED": None,
    "SENT": None,
    "LABEL_CREATED": None,

    # Kurier potwierdzil odbior
    "COLLECTED": "wyslano",
    "PICKED_UP_BY_CARRIER": "wyslano",
    "IN_TRANSIT": "wyslano",

    # Ostatnia mila
    "OUT_FOR_DELIVERY": "w_transporcie",

    # W punkcie odbioru (scalone: w_punkcie + gotowe_do_odbioru)
    "AT_PICKUP_POINT": "w_punkcie",
    "READY_TO_PICKUP": "w_punkcie",
    "PICKUP_REMINDER": "w_punkcie",
    "AVIZO": "w_punkcie",

    # Dostarczono
    "DELIVERED": "dostarczono",
    "PICKED_UP": "dostarczono",

    # Problemy z dostawa
    "NOT_DELIVERED": "problem_z_dostawa",
    "LOST": "problem_z_dostawa",
    "FAILED_DELIVERY": "problem_z_dostawa",

    # Zwroty i anulacje
    "RETURNED": "zwrot",
    "RETURNED_TO_SENDER": "zwrot",
    "CANCELLED": "anulowano",

    # Nieznane
    "OTHER": None,
}


# ── Allegro checkout-forms order status → status wewnetrzny ────────

ALLEGRO_ORDER_STATUS_MAP = {
    "BOUGHT": "pobrano",
    "FILLED_IN": "pobrano",
    "READY_FOR_PROCESSING": "pobrano",  # wydrukowano ustawiamy dopiero po wydruku
    "CANCELLED": "anulowano",
}


# ── Allegro fulfillment status → status wewnetrzny ─────────────────

ALLEGRO_FULFILLMENT_MAP = {
    "NEW": "pobrano",
    "PROCESSING": None,          # drukowanie zarzadzamy wewnetrznie
    "READY_FOR_SHIPMENT": None,  # pakowanie zarzadzamy wewnetrznie
    "SENT": None,                # ignorowane — nie jest potwierdzeniem kuriera
    "PICKED_UP": "dostarczono",
    "CANCELLED": "anulowano",
}


# ── Allegro Shipment Management tracking → status wewnetrzny ───────

SHIPMENT_TRACKING_MAP = {
    "PENDING": None,  # nie jest potwierdzeniem kuriera
    "IN_TRANSIT": "wyslano",
    "RELEASED_FOR_DELIVERY": "w_transporcie",
    "AVAILABLE_FOR_PICKUP": "w_punkcie",
    "NOTICE_LEFT": "w_punkcie",
    "DELIVERED": "dostarczono",
    "RETURNED": "zwrot",
    "ISSUE": "problem_z_dostawa",
}


# ── Admin UI: badge text + CSS class ───────────────────────────────

STATUS_DISPLAY = {
    "pobrano": ("Pobrano", "bg-light text-dark"),
    "wydrukowano": ("Wydrukowano", "bg-info"),
    "blad_druku": ("Błąd druku", "bg-danger"),
    "spakowano": ("Spakowano", "bg-info"),
    "wyslano": ("Wysłano", "bg-primary"),
    "w_transporcie": ("W transporcie", "bg-warning text-dark"),
    "w_punkcie": ("W punkcie odbioru", "bg-success"),
    "dostarczono": ("Dostarczono", "bg-success"),
    "problem_z_dostawa": ("Problem z dostawą", "bg-danger"),
    "zwrot": ("Zwrot", "bg-danger"),
    "anulowano": ("Anulowano", "bg-dark"),
}

# Fallback dla starych statusow jeszcze w bazie (przed migracja)
_LEGACY_STATUS_DISPLAY = {
    "niewydrukowano": STATUS_DISPLAY["pobrano"],
    "przekazano_kurierowi": STATUS_DISPLAY["wyslano"],
    "w_drodze": STATUS_DISPLAY["w_transporcie"],
    "gotowe_do_odbioru": STATUS_DISPLAY["w_punkcie"],
    "niedostarczono": STATUS_DISPLAY["problem_z_dostawa"],
    "zagubiono": STATUS_DISPLAY["problem_z_dostawa"],
    "awizo": STATUS_DISPLAY["w_punkcie"],
    "zakończono": STATUS_DISPLAY["dostarczono"],
}


def get_status_display(status: str) -> tuple:
    """Zwraca (text, css_class) dla statusu. Obsluguje legacy statusy."""
    return (
        STATUS_DISPLAY.get(status)
        or _LEGACY_STATUS_DISPLAY.get(status)
        or (status, "bg-secondary")
    )


# ── Status → typ emaila ────────────────────────────────────────────

STATUS_EMAIL_MAP = {
    "pobrano": "confirmation",
    "wyslano": "shipment",
    "dostarczono": "delivery",
    "zwrot": "correction",
}


# ── Klient-facing display (publiczna strona zamowienia) ─────────────

CUSTOMER_STATUS_DISPLAY = {
    "pobrano": ("Przyjęte do realizacji", "info", "bi-check-circle"),
    "wydrukowano": ("Przygotowane do wysyłki", "primary", "bi-printer"),
    "blad_druku": ("Przygotowywane", "info", "bi-hourglass-split"),
    "spakowano": ("Spakowane", "primary", "bi-box-seam"),
    "wyslano": ("Nadane", "warning", "bi-truck"),
    "w_transporcie": ("W drodze", "warning", "bi-truck"),
    "w_punkcie": ("Gotowe do odbioru", "success", "bi-geo-alt"),
    "dostarczono": ("Dostarczone", "success", "bi-check2-circle"),
    "problem_z_dostawa": ("Problem z dostawą", "danger", "bi-exclamation-triangle"),
    "anulowano": ("Anulowane", "danger", "bi-x-circle"),
    "zwrot": ("Zwrot", "danger", "bi-arrow-return-left"),
}

# Progress bar etapy klienta
CUSTOMER_STAGES = [
    ("accepted", "Przyjęte", "bi-check-circle"),
    ("preparing", "Przygotowywane", "bi-box-seam"),
    ("shipped", "Wysyłka", "bi-truck"),
    ("delivered", "Dostarczone", "bi-check2-circle"),
]

CUSTOMER_STAGE_MAP = {
    "pobrano": 0,
    "wydrukowano": 1,
    "blad_druku": 1,
    "spakowano": 1,
    "wyslano": 2,
    "w_transporcie": 2,
    "w_punkcie": 3,
    "dostarczono": 3,
}


# ── Filtry listy zamowien ───────────────────────────────────────────

STATUS_FILTER_GROUPS = {
    "w_realizacji": ["pobrano", "wydrukowano", "blad_druku", "spakowano"],
    "w_transporcie": ["wyslano", "w_transporcie", "w_punkcie"],
    "zakonczone": ["dostarczono"],
    "problem": ["problem_z_dostawa", "zwrot", "anulowano"],
}
