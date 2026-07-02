"""Canary wykrywajacy nagly, nienaturalny spadek liczby rekordow w bazie.

Zabezpieczenie wprowadzone po incydencie z 2026-07-01 (przypadkowy DROP ALL
na bazie produkcyjnej przez ``pytest`` odpalony w kontenerze produkcyjnym).
Celem jest wykrycie podobnej sytuacji w ciagu jednego cyklu synchronizacji
(do ~10 minut), a nie po godzinach/dniach.

WAZNE - gdzie trzymamy punkt odniesienia (high-water-mark):
Stan jest zapisywany w PLIKU na dysku (``data_integrity_hwm.json`` obok
``DB_PATH``, czyli w katalogu zamontowanym z hosta - ``./data:/app/data`` w
docker-compose.yml), a NIE w bazie danych ani w ``settings_store``. Gdyby
zapisac go w bazie, ``DROP ALL`` wyzerowalby rowniez punkt odniesienia i
canary NIE zauwazylby wlasnie takiego incydentu, ktoremu ma zapobiegac.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Dict

from sqlalchemy import func

logger = logging.getLogger(__name__)

# Ponizej tej wartosci historyczne maksimum tabeli nie jest brane pod uwage -
# unika falszywych alarmow na swiezej/malej bazie (dev, testy, nowy sklep).
MIN_ROWS_FOR_CHECK = 10

# Jesli aktualna liczba rekordow spadnie ponizej tego ulamka historycznego
# maksimum - odpalamy alarm.
DROP_RATIO_THRESHOLD = 0.5


def _hwm_file_path() -> Path:
    from ..config import settings

    db_path = getattr(settings, "DB_PATH", None) or "/app/data/database.db"
    return Path(db_path).with_name("data_integrity_hwm.json")


def _load_hwm() -> Dict[str, int]:
    path = _hwm_file_path()
    try:
        if path.exists():
            return json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        logger.warning("Canary: nie udalo sie odczytac %s: %s", path, exc)
    return {}


def _save_hwm(data: Dict[str, int]) -> None:
    path = _hwm_file_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(data))
        os.replace(tmp_path, path)
    except OSError as exc:
        logger.warning("Canary: nie udalo sie zapisac %s: %s", path, exc)


def _watched_models() -> dict:
    from ..models.orders import Order, OrderProduct
    from ..models.products import Product, ProductSize
    from ..models.users import User

    return {
        "orders": Order,
        "order_products": OrderProduct,
        "products": Product,
        "product_sizes": ProductSize,
        "users": User,
    }


def check_data_integrity() -> dict:
    """Porownaj liczbe rekordow w kluczowych tabelach z historycznym maksimum
    zapisanym w pliku na dysku. Przy podejrzanym spadku wysyla natychmiastowy
    alert (Messenger + email, patrz ``notifications.alerts.send_critical_alert``).

    Returns
    -------
    dict {"checked": int, "alerts": list[str]}
    """
    from ..db import get_session
    from ..notifications.alerts import send_critical_alert

    stats: dict = {"checked": 0, "alerts": []}
    hwm = _load_hwm()
    hwm_changed = False

    with get_session() as db:
        for table_name, model in _watched_models().items():
            stats["checked"] += 1
            try:
                current = db.query(func.count()).select_from(model).scalar() or 0
            except Exception as exc:
                logger.error("Canary: blad liczenia rekordow %s: %s", table_name, exc)
                continue

            previous_max = hwm.get(table_name, 0)

            if (
                previous_max >= MIN_ROWS_FOR_CHECK
                and current < previous_max * DROP_RATIO_THRESHOLD
            ):
                message = (
                    f"Tabela '{table_name}' ma teraz {current} rekordow, "
                    f"wczesniej mialo maksymalnie {previous_max} "
                    f"(spadek > {int((1 - DROP_RATIO_THRESHOLD) * 100)}%). "
                    "Mozliwa utrata danych - sprawdz baze NATYCHMIAST."
                )
                logger.critical("DATA INTEGRITY ALERT: %s", message)
                stats["alerts"].append(message)
                send_critical_alert(
                    "ALARM: mozliwa utrata danych w bazie magazynu", message
                )

            if current > previous_max:
                hwm[table_name] = current
                hwm_changed = True

    if hwm_changed:
        _save_hwm(hwm)

    return stats


__all__ = ["check_data_integrity", "MIN_ROWS_FOR_CHECK", "DROP_RATIO_THRESHOLD"]
