"""Parsowanie terminow dostaw Allegro."""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Optional

POLISH_MONTHS = {
    "sty": 1,
    "lut": 2,
    "mar": 3,
    "kwi": 4,
    "maj": 5,
    "cze": 6,
    "lip": 7,
    "sie": 8,
    "wrz": 9,
    "paz": 10,
    "lis": 11,
    "gru": 12,
}


def _easter_date(year: int) -> date:
    """Oblicza date Wielkanocy algorytmem Meeusa/Jonesa/Butchera."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    weekday_offset = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * weekday_offset) // 451
    month = (h + weekday_offset - 7 * m + 114) // 31
    day = ((h + weekday_offset - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _polish_holidays(year: int) -> set[date]:
    """Zwraca zbior polskich swiat ustawowo wolnych od pracy."""
    easter = _easter_date(year)
    return {
        date(year, 1, 1),
        date(year, 1, 6),
        easter,
        easter + timedelta(days=1),
        date(year, 5, 1),
        date(year, 5, 3),
        easter + timedelta(days=60),
        date(year, 8, 15),
        date(year, 11, 1),
        date(year, 11, 11),
        date(year, 12, 25),
        date(year, 12, 26),
    }


def _business_days_between(start: date, end: date) -> int:
    """Liczy dni robocze miedzy datami, bez weekendow i polskich swiat."""
    if end <= start:
        return 0
    holidays = _polish_holidays(start.year)
    if end.year != start.year:
        holidays |= _polish_holidays(end.year)
    count = 0
    current = start + timedelta(days=1)
    while current <= end:
        if current.weekday() < 5 and current not in holidays:
            count += 1
        current += timedelta(days=1)
    return count


def parse_delivery_days(text: str) -> Optional[int]:
    """Parsuje tekst dostawy na liczbe dni roboczych."""
    if not text:
        return None
    delivery_text = text.lower().strip()
    today = date.today()

    if re.match(r"^dostawa\s+od\s+\d", delivery_text):
        return 99

    match = re.search(r"dostawa\s+za\s+(\d+)\s*[–-]\s*(\d+)\s*dni", delivery_text)
    if match:
        avg_days = (int(match.group(1)) + int(match.group(2))) // 2
        return _business_days_between(today, today + timedelta(days=avg_days))

    match = re.search(r"dostawa\s+za\s+(\d+)\s*dni", delivery_text)
    if match:
        return _business_days_between(today, today + timedelta(days=int(match.group(1))))

    cleaned = re.sub(
        r"^dostawa\s+(?:pon|wt|[sś]r|czw|pt|sob|niedz)\.?\s*",
        "dostawa ",
        delivery_text,
    )
    match = re.search(
        r"(\d{1,2})\s+(sty|lut|mar|kwi|maj|cze|lip|sie|wrz|pa[zź]|lis|gru)",
        cleaned,
    )
    if match:
        day = int(match.group(1))
        month_str = match.group(2).replace("ź", "z")
        month = POLISH_MONTHS.get(month_str, 1)
        try:
            target = date(today.year, month, day)
            if target < today:
                target = date(today.year + 1, month, day)
            return _business_days_between(today, target)
        except ValueError:
            pass

    days_of_week = {
        "poniedzialek": 0,
        "poniedziałek": 0,
        "poniedział": 0,
        "pon": 0,
        "wtorek": 1,
        "wtor": 1,
        "wt": 1,
        "sroda": 2,
        "środa": 2,
        "srod": 2,
        "środ": 2,
        "sr": 2,
        "śr": 2,
        "czwartek": 3,
        "czwart": 3,
        "czw": 3,
        "piatek": 4,
        "piątek": 4,
        "piąt": 4,
        "piat": 4,
        "pt": 4,
        "sobota": 5,
        "sobot": 5,
        "sobo": 5,
        "sob": 5,
        "niedziela": 6,
        "niedziel": 6,
        "niedz": 6,
    }
    for day_name, day_num in days_of_week.items():
        if day_name in delivery_text:
            days_ahead = day_num - today.weekday()
            if days_ahead <= 0:
                days_ahead += 7
            return _business_days_between(today, today + timedelta(days=days_ahead))

    if "pojutrze" in delivery_text:
        return _business_days_between(today, today + timedelta(days=2))
    if "jutro" in delivery_text:
        return _business_days_between(today, today + timedelta(days=1))
    if "dzisiaj" in delivery_text or "dzis" in delivery_text or "dziś" in delivery_text:
        return 0

    return None