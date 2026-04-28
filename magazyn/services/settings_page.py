"""Serwis widoku ustawien aplikacji."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass

from ..env_info import ENV_INFO
from ..settings_io import HIDDEN_KEYS
from ..settings_store import SettingsPersistenceError, settings_store
from .fixed_costs import list_fixed_costs
from .print_agent_config import parse_time_str


BOOLEAN_KEYS = {
    "ENABLE_MONTHLY_REPORTS",
    "ENABLE_WEEKLY_REPORTS",
    "ALLEGRO_AUTORESPONDER_ENABLED",
}

SETTINGS_GROUPS = {
    "ALLEGRO_CLIENT_ID": ("Allegro", "bi-shop"),
    "ALLEGRO_CLIENT_SECRET": ("Allegro", "bi-shop"),
    "ALLEGRO_REDIRECT_URI": ("Allegro", "bi-shop"),
    "ALLEGRO_ACCESS_TOKEN": ("Allegro", "bi-shop"),
    "ALLEGRO_REFRESH_TOKEN": ("Allegro", "bi-shop"),
    "COMMISSION_ALLEGRO": ("Allegro", "bi-shop"),
    "PRICE_MAX_DISCOUNT_PERCENT": ("Allegro", "bi-shop"),
    "ALLEGRO_AUTORESPONDER_ENABLED": ("Allegro", "bi-shop"),
    "ALLEGRO_AUTORESPONDER_MESSAGE": ("Allegro", "bi-shop"),
    "WFIRMA_ACCESS_KEY": ("wFirma", "bi-receipt"),
    "WFIRMA_SECRET_KEY": ("wFirma", "bi-receipt"),
    "WFIRMA_APP_KEY": ("wFirma", "bi-receipt"),
    "WFIRMA_COMPANY_ID": ("wFirma", "bi-receipt"),
    "PRINTER_NAME": ("Drukowanie", "bi-printer"),
    "CUPS_SERVER": ("Drukowanie", "bi-printer"),
    "CUPS_PORT": ("Drukowanie", "bi-printer"),
    "POLL_INTERVAL": ("Drukowanie", "bi-printer"),
    "QUIET_HOURS_START": ("Drukowanie", "bi-printer"),
    "QUIET_HOURS_END": ("Drukowanie", "bi-printer"),
    "PRINTED_EXPIRY_DAYS": ("Drukowanie", "bi-printer"),
    "SENDER_NAME": ("Nadawca przesylek", "bi-box-seam"),
    "SENDER_COMPANY": ("Nadawca przesylek", "bi-box-seam"),
    "SENDER_STREET": ("Nadawca przesylek", "bi-box-seam"),
    "SENDER_CITY": ("Nadawca przesylek", "bi-box-seam"),
    "SENDER_ZIPCODE": ("Nadawca przesylek", "bi-box-seam"),
    "SENDER_EMAIL": ("Nadawca przesylek", "bi-box-seam"),
    "SENDER_PHONE": ("Nadawca przesylek", "bi-box-seam"),
    "PACKAGING_COST": ("Sprzedaz", "bi-cash"),
    "PAGE_ACCESS_TOKEN": ("Powiadomienia", "bi-bell"),
    "RECIPIENT_ID": ("Powiadomienia", "bi-bell"),
    "LOW_STOCK_THRESHOLD": ("Powiadomienia", "bi-bell"),
    "ALERT_EMAIL": ("Powiadomienia", "bi-bell"),
    "SMTP_SERVER": ("E-mail", "bi-envelope"),
    "SMTP_PORT": ("E-mail", "bi-envelope"),
    "SMTP_USERNAME": ("E-mail", "bi-envelope"),
    "SMTP_PASSWORD": ("E-mail", "bi-envelope"),
    "EMAIL_FROM_NAME": ("E-mail", "bi-envelope"),
    "APP_BASE_URL": ("E-mail", "bi-envelope"),
    "ENABLE_WEEKLY_REPORTS": ("E-mail", "bi-envelope"),
    "ENABLE_MONTHLY_REPORTS": ("E-mail", "bi-envelope"),
    "API_RATE_LIMIT_CALLS": ("API", "bi-speedometer"),
    "API_RATE_LIMIT_PERIOD": ("API", "bi-speedometer"),
    "API_RETRY_ATTEMPTS": ("API", "bi-speedometer"),
    "API_RETRY_BACKOFF_INITIAL": ("API", "bi-speedometer"),
    "API_RETRY_BACKOFF_MAX": ("API", "bi-speedometer"),
    "SECRET_KEY": ("System", "bi-gear"),
    "TIMEZONE": ("System", "bi-gear"),
    "LOG_LEVEL": ("System", "bi-gear"),
    "LOG_FILE": ("System", "bi-gear"),
    "DB_PATH": ("System", "bi-gear"),
    "DATABASE_URL": ("System", "bi-gear"),
}


@dataclass(frozen=True)
class SettingsUpdateResult:
    message: str
    category: str
    should_reload_agent: bool = False


def build_settings_context(logger=None, on_error=None) -> dict:
    all_values = settings_store.as_ordered_dict(
        include_hidden=True,
        logger=logger,
        on_error=on_error,
    )
    values = _visible_values(all_values)
    sales_keys = _sales_keys(values)
    settings_list = _settings_entries(values, sales_keys)
    fixed_costs_list, total_fixed_costs = list_fixed_costs()
    return {
        "settings": settings_list,
        "grouped_settings": _group_settings(settings_list),
        "db_path_notice": bool(all_values.get("DB_PATH")),
        "boolean_keys": BOOLEAN_KEYS,
        "fixed_costs": fixed_costs_list,
        "total_fixed_costs": total_fixed_costs,
    }


def update_settings_from_form(form, logger=None) -> SettingsUpdateResult:
    all_values = settings_store.as_ordered_dict(include_hidden=True, logger=logger)
    values = _visible_values(all_values)
    sales_keys = _sales_keys(values)
    updates = {
        key: form.get(key, values.get(key, ""))
        for key in list(values.keys())
        if key not in sales_keys
    }
    for time_key in ("QUIET_HOURS_START", "QUIET_HOURS_END"):
        try:
            parse_time_str(updates.get(time_key, values.get(time_key, "")))
        except ValueError:
            return SettingsUpdateResult("Niepoprawny format godziny (hh:mm)", "error")
    try:
        settings_store.update(updates)
    except SettingsPersistenceError as exc:
        if logger:
            logger.error("Failed to persist settings submitted via the admin panel", exc_info=exc)
        return SettingsUpdateResult(
            "Nie można zapisać ustawień, ponieważ baza konfiguracji jest w trybie tylko do odczytu.",
            "error",
        )
    return SettingsUpdateResult("Zapisano ustawienia.", "success", should_reload_agent=True)


def _visible_values(all_values) -> OrderedDict:
    return OrderedDict((key, value) for key, value in all_values.items() if key not in HIDDEN_KEYS)


def _sales_keys(values) -> list[str]:
    keywords = ("SHIPPING", "COMMISSION", "EMAIL", "SMTP", "PRICE_MAX_DISCOUNT")
    return [key for key in values.keys() if any(word in key for word in keywords)]


def _settings_entries(values, sales_keys) -> list[dict]:
    entries = []
    for key, value in values.items():
        if key in sales_keys:
            continue
        label, desc = ENV_INFO.get(key, (key, None))
        group_name, group_icon = SETTINGS_GROUPS.get(key, ("Inne", "bi-three-dots"))
        entries.append(
            {
                "key": key,
                "label": label,
                "desc": desc,
                "value": value,
                "group": group_name,
                "group_icon": group_icon,
            }
        )
    return entries


def _group_settings(settings_list) -> OrderedDict:
    grouped_settings = OrderedDict()
    for item in settings_list:
        group_name = item["group"]
        if group_name not in grouped_settings:
            grouped_settings[group_name] = {"icon": item["group_icon"], "entries": []}
        grouped_settings[group_name]["entries"].append(item)
    return grouped_settings


__all__ = ["BOOLEAN_KEYS", "SettingsUpdateResult", "build_settings_context", "update_settings_from_form"]