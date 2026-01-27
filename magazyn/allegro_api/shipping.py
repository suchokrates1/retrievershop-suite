"""
Szacowanie kosztow wysylki Allegro Smart.

Tabela kosztow na podstawie:
https://help.allegro.com/pl/sell/a/allegro-smart-na-allegro-pl-informacje-dla-sprzedajacych-9g0rWRXKxHG
Aktualizacja: Styczen 2026
"""
from decimal import Decimal


# Progi wartosci zamowienia (w PLN)
ALLEGRO_SMART_THRESHOLDS = [
    (Decimal("30.00"), Decimal("44.99")),
    (Decimal("45.00"), Decimal("64.99")),
    (Decimal("65.00"), Decimal("99.99")),
    (Decimal("100.00"), Decimal("149.99")),
    (Decimal("150.00"), Decimal("999999.99")),
]

# Koszty wysylki dla sprzedajacego wg metody dostawy i progu cenowego
# Format: {klucz_metody: [koszt_prog1, koszt_prog2, koszt_prog3, koszt_prog4, koszt_prog5]}
ALLEGRO_SMART_SHIPPING_COSTS = {
    # === AUTOMATY PACZKOWE I PUNKTY ODBIORU ===
    # Allegro Paczkomaty InPost
    "paczkomaty_inpost": [Decimal("1.59"), Decimal("3.09"), Decimal("4.99"), Decimal("7.59"), Decimal("9.99")],
    "allegro paczkomaty inpost": [Decimal("1.59"), Decimal("3.09"), Decimal("4.99"), Decimal("7.59"), Decimal("9.99")],
    "inpost_paczkomaty": [Decimal("1.59"), Decimal("3.09"), Decimal("4.99"), Decimal("7.59"), Decimal("9.99")],
    
    # Allegro Automat DHL BOX 24/7 (Allegro Delivery)
    "dhl_box": [Decimal("0.99"), Decimal("1.89"), Decimal("3.59"), Decimal("5.89"), Decimal("7.79")],
    "allegro automat dhl box": [Decimal("0.99"), Decimal("1.89"), Decimal("3.59"), Decimal("5.89"), Decimal("7.79")],
    
    # Allegro Automat Pocztex
    "automat_pocztex": [Decimal("1.29"), Decimal("2.49"), Decimal("4.29"), Decimal("6.69"), Decimal("8.89")],
    "allegro automat pocztex": [Decimal("1.29"), Decimal("2.49"), Decimal("4.29"), Decimal("6.69"), Decimal("8.89")],
    
    # Allegro Automat ORLEN Paczka (Allegro Delivery)
    "orlen_automat": [Decimal("0.99"), Decimal("1.89"), Decimal("3.59"), Decimal("5.89"), Decimal("7.79")],
    "allegro automat orlen paczka": [Decimal("0.99"), Decimal("1.89"), Decimal("3.59"), Decimal("5.89"), Decimal("7.79")],
    "orlen paczka": [Decimal("0.99"), Decimal("1.89"), Decimal("3.59"), Decimal("5.89"), Decimal("7.79")],
    
    # Allegro Automat DPD Pickup (Allegro Delivery)
    "dpd_automat": [Decimal("0.99"), Decimal("1.89"), Decimal("3.59"), Decimal("5.89"), Decimal("7.79")],
    "allegro automat dpd pickup": [Decimal("0.99"), Decimal("1.89"), Decimal("3.59"), Decimal("5.89"), Decimal("7.79")],
    
    # Allegro One Box (Allegro Delivery)
    "one_box": [Decimal("0.99"), Decimal("1.89"), Decimal("3.59"), Decimal("5.89"), Decimal("7.79")],
    "allegro one box": [Decimal("0.99"), Decimal("1.89"), Decimal("3.59"), Decimal("5.89"), Decimal("7.79")],
    
    # Allegro Odbiór w Punkcie Pocztex
    "punkt_pocztex": [Decimal("1.29"), Decimal("2.49"), Decimal("4.29"), Decimal("6.69"), Decimal("8.89")],
    "allegro odbior w punkcie pocztex": [Decimal("1.29"), Decimal("2.49"), Decimal("4.29"), Decimal("6.69"), Decimal("8.89")],
    
    # Allegro Odbiór w Punkcie DPD Pickup (bez Allegro Delivery)
    "punkt_dpd": [Decimal("1.59"), Decimal("3.09"), Decimal("4.99"), Decimal("7.59"), Decimal("9.99")],
    
    # Allegro Odbiór w Punkcie DPD Pickup (Allegro Delivery)
    "punkt_dpd_delivery": [Decimal("0.99"), Decimal("1.89"), Decimal("3.59"), Decimal("5.89"), Decimal("7.79")],
    "allegro odbior w punkcie dpd pickup": [Decimal("0.99"), Decimal("1.89"), Decimal("3.59"), Decimal("5.89"), Decimal("7.79")],
    
    # Allegro Odbiór w Punkcie DHL (Allegro Delivery)
    "punkt_dhl": [Decimal("0.99"), Decimal("1.89"), Decimal("3.59"), Decimal("5.89"), Decimal("7.79")],
    "allegro odbior w punkcie dhl": [Decimal("0.99"), Decimal("1.89"), Decimal("3.59"), Decimal("5.89"), Decimal("7.79")],
    
    # Allegro Odbiór w Punkcie ORLEN Paczka (Allegro Delivery)
    "punkt_orlen": [Decimal("0.99"), Decimal("1.89"), Decimal("3.59"), Decimal("5.89"), Decimal("7.79")],
    "allegro odbior w punkcie orlen paczka": [Decimal("0.99"), Decimal("1.89"), Decimal("3.59"), Decimal("5.89"), Decimal("7.79")],
    
    # Allegro One Punkt (Allegro Delivery)
    "one_punkt": [Decimal("0.99"), Decimal("1.89"), Decimal("3.59"), Decimal("5.89"), Decimal("7.79")],
    "allegro one punkt": [Decimal("0.99"), Decimal("1.89"), Decimal("3.59"), Decimal("5.89"), Decimal("7.79")],
    
    # === PRZESYLKI KURIERSKIE ===
    # Allegro Kurier DPD (bez Allegro Delivery)
    "kurier_dpd": [Decimal("1.99"), Decimal("3.99"), Decimal("5.79"), Decimal("9.09"), Decimal("11.49")],
    "allegro kurier dpd": [Decimal("1.99"), Decimal("3.99"), Decimal("5.79"), Decimal("9.09"), Decimal("11.49")],
    
    # Allegro Kurier DPD (Allegro Delivery)
    "kurier_dpd_delivery": [Decimal("1.79"), Decimal("3.69"), Decimal("5.39"), Decimal("8.59"), Decimal("10.89")],
    
    # Allegro Kurier DHL (Allegro Delivery)
    "kurier_dhl": [Decimal("1.79"), Decimal("3.69"), Decimal("5.39"), Decimal("8.59"), Decimal("10.89")],
    "allegro kurier dhl": [Decimal("1.79"), Decimal("3.69"), Decimal("5.39"), Decimal("8.59"), Decimal("10.89")],
    "dhl": [Decimal("1.79"), Decimal("3.69"), Decimal("5.39"), Decimal("8.59"), Decimal("10.89")],
    
    # Allegro Kurier Pocztex
    "kurier_pocztex": [Decimal("1.99"), Decimal("3.99"), Decimal("5.79"), Decimal("9.09"), Decimal("11.49")],
    "allegro kurier pocztex": [Decimal("1.99"), Decimal("3.99"), Decimal("5.79"), Decimal("9.09"), Decimal("11.49")],
    
    # Allegro One Kurier (Allegro Delivery)
    "one_kurier": [Decimal("1.79"), Decimal("3.69"), Decimal("5.39"), Decimal("8.59"), Decimal("10.89")],
    "allegro one kurier": [Decimal("1.79"), Decimal("3.69"), Decimal("5.39"), Decimal("8.59"), Decimal("10.89")],
    
    # Allegro Przesylka polecona
    "przesylka_polecona": [Decimal("0.79"), Decimal("1.49"), Decimal("2.29"), Decimal("3.49"), Decimal("4.29")],
    "allegro przesylka polecona": [Decimal("0.79"), Decimal("1.49"), Decimal("2.29"), Decimal("3.49"), Decimal("4.29")],
    
    # Allegro MiniPrzesylka
    "miniprzesylka": [Decimal("0.79"), Decimal("1.49"), Decimal("2.29"), Decimal("3.49"), Decimal("4.29")],
    "allegro miniprzesylka": [Decimal("0.79"), Decimal("1.49"), Decimal("2.29"), Decimal("3.49"), Decimal("4.29")],
}

# Domyslne koszty (InPost Paczkomaty - najpopularniejsza metoda)
DEFAULT_SHIPPING_COSTS = [Decimal("1.59"), Decimal("3.09"), Decimal("4.99"), Decimal("7.59"), Decimal("9.99")]


def _normalize_delivery_method(delivery_method: str) -> str:
    """Normalizuj nazwe metody dostawy do klucza slownikowego."""
    if not delivery_method:
        return ""
    normalized = delivery_method.lower().strip()
    normalized = normalized.replace("ó", "o").replace("ł", "l").replace("ą", "a")
    normalized = normalized.replace("ę", "e").replace("ś", "s").replace("ż", "z")
    normalized = normalized.replace("ź", "z").replace("ć", "c").replace("ń", "n")
    return normalized


def _get_threshold_index(order_value: Decimal) -> int:
    """Zwroc indeks progu cenowego dla danej wartosci zamowienia."""
    for i, (min_val, max_val) in enumerate(ALLEGRO_SMART_THRESHOLDS):
        if min_val <= order_value <= max_val:
            return i
    if order_value >= Decimal("150.00"):
        return 4
    return 0


def estimate_allegro_shipping_cost(delivery_method: str, order_value: Decimal) -> dict:
    """
    Szacuj koszt wysylki Allegro Smart na podstawie metody dostawy i wartosci zamowienia.
    
    Args:
        delivery_method: Nazwa metody dostawy (np. "Allegro Paczkomaty InPost")
        order_value: Wartosc zamowienia w PLN
    
    Returns:
        dict: {
            "estimated_cost": Decimal - szacowany koszt,
            "threshold_index": int - indeks progu cenowego (0-4),
            "threshold_range": str - zakres cenowy (np. "100.00-149.99 PLN"),
            "delivery_method_matched": str - dopasowana metoda lub "default",
            "is_estimate": True - zawsze True, to szacunek
        }
    """
    normalized = _normalize_delivery_method(delivery_method)
    threshold_idx = _get_threshold_index(order_value)
    
    costs = None
    matched_method = "default"
    
    if normalized in ALLEGRO_SMART_SHIPPING_COSTS:
        costs = ALLEGRO_SMART_SHIPPING_COSTS[normalized]
        matched_method = normalized
    else:
        for key, cost_list in ALLEGRO_SMART_SHIPPING_COSTS.items():
            if key in normalized or normalized in key:
                costs = cost_list
                matched_method = key
                break
    
    if costs is None:
        costs = DEFAULT_SHIPPING_COSTS
        matched_method = "default (inpost)"
    
    estimated_cost = costs[threshold_idx]
    
    min_val, max_val = ALLEGRO_SMART_THRESHOLDS[threshold_idx]
    if threshold_idx == 4:
        threshold_range = f"od {min_val} PLN"
    else:
        threshold_range = f"{min_val}-{max_val} PLN"
    
    return {
        "estimated_cost": estimated_cost,
        "threshold_index": threshold_idx,
        "threshold_range": threshold_range,
        "delivery_method_matched": matched_method,
        "is_estimate": True,
    }
