#!/usr/bin/env python3
"""Jednorazowy skrypt naprawczy: odtworzenie recznego zamowienia OLX
utraconego przy wyczyszczeniu bazy produkcyjnej (2026-07-01).

Oryginalne zamowienie manual_1782919998_9bc18c4f zostalo utworzone
2026-07-01 17:33:18 (patrz agent.log), ale proba automatycznego utworzenia
przesylki przez Allegro Shipment API zakonczyla sie bledem walidacji adresu
(brak numeru budynku) - etykieta zostala wiec wydrukowana RECZNIE poza
systemem (OLX, kurier InPost), a zamowienie nigdy nie dostalo statusu
"wyslano" w bazie. Po zdropowaniu bazy dane oryginalnego klienta/adresu
zostaly utracone bezpowrotnie - odtwarzamy tylko fakty potwierdzone przez
wlasciciela sklepu:
    - produkt: Szelki dla psa Truelove Tropical, XL, Turkusowy
      (dopasowane po koszcie zakupu z logu: purchase_cost=134.33 zl,
      co odpowiada dokladnie partii zakupowej id=425, price=134.33)
    - cena: 200 zl brutto
    - prowizja OLX: 7,5% => 15 zl
    - wysylka: 0 zl
    - kurier: InPost, nr przesylki: 620999681824160672994529
    - status: wyslane (etykieta drukowana recznie)

Dane klienta/adresu SA NIEZNANE i oznaczone wprost jako placeholder -
nie sa zmyslone jako prawdziwe dane osobowe.

Uzycie:
    python scripts/ops/recovery_restore_manual_olx_order.py --dry-run
    python scripts/ops/recovery_restore_manual_olx_order.py --commit
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from magazyn.factory import create_app
from magazyn.db import get_session
from magazyn.models.orders import Order
from magazyn.models.products import ProductSize
from magazyn.services.order_sync import sync_order_from_data
from magazyn.services.order_status import add_order_status
from magazyn.services.manual_order_actions import finalize_manual_order_creation
from magazyn.domain.inventory import consume_order_stock

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("recovery-olx")

ORDER_ID = "manual_1782919998_9bc18c4f"
PRODUCT_BARCODE = "6971818795201"  # Szelki Truelove Tropical XL Turkusowy (product_id=44, size_id=276)
SALE_PRICE = 200.0
COMMISSION_PCT = 7.5
COMMISSION_FEE = round(SALE_PRICE * COMMISSION_PCT / 100, 2)  # 15.00
TRACKING_NUMBER = "620999681824160672994529"

ORDER_DATA = {
    "order_id": ORDER_ID,
    "external_order_id": None,
    "platform": "olx",
    "customer": "Klient OLX (dane utracone - odtworzone po awarii bazy)",
    "delivery_fullname": "Klient OLX (dane utracone - odtworzone po awarii bazy)",
    "email": None,
    "phone": None,
    "delivery_company": None,
    "delivery_address": "NIEZNANE - dane utracone po awarii bazy 2026-07-01",
    "delivery_postcode": None,
    "delivery_city": "NIEZNANE",
    "delivery_country": "Polska",
    "delivery_country_code": "PL",
    "delivery_method": "Kurier InPost",
    "delivery_price": 0.0,
    "delivery_package_nr": TRACKING_NUMBER,
    "payment_method": "przelew",
    "payment_method_cod": "0",
    "payment_done": SALE_PRICE,
    "want_invoice": "0",
    "invoice_fullname": None,
    "invoice_company": None,
    "invoice_nip": None,
    "invoice_address": None,
    "invoice_postcode": None,
    "invoice_city": None,
    "invoice_country": "Polska",
    "user_comments": None,
    "admin_comments": (
        "Zamowienie odtworzone recznie po zdropowaniu bazy produkcyjnej 2026-07-01. "
        "Oryginalne dane klienta/adresu SA UTRACONE (nie do odzyskania). "
        "Potwierdzone fakty od wlasciciela sklepu: cena 200 zl, prowizja OLX 7,5% (15 zl), "
        "wysylka 0 zl, InPost nr 620999681824160672994529, status: wyslane. "
        "Etykieta zostala wydrukowana RECZNIE poza systemem, ponieważ automatyczne "
        "tworzenie przesylki przez Allegro Shipment API zakonczylo sie bledem "
        "walidacji adresu (input.receiver.street - brak numeru budynku), patrz agent.log 17:33:48."
    ),
    "currency": "PLN",
    "confirmed": True,
    "date_add": 1782919998,
    "date_confirmed": 1782919998,
    "products": [
        {
            "name": "Szelki dla psa Truelove Tropical XL Turkusowy",
            "ean": PRODUCT_BARCODE,
            "quantity": 1,
            "price_brutto": SALE_PRICE,
            "commission_fee": COMMISSION_FEE,
        }
    ],
}


def main() -> None:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--commit", action="store_true")
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        with get_session() as db:
            existing = db.query(Order).filter(Order.order_id == ORDER_ID).first()
            if existing:
                logger.warning("Zamowienie %s JUZ ISTNIEJE w bazie - przerywam!", ORDER_ID)
                return

            product_size = (
                db.query(ProductSize).filter(ProductSize.barcode == PRODUCT_BARCODE).first()
            )
            if not product_size:
                logger.error("Nie znaleziono ProductSize dla barcode=%s", PRODUCT_BARCODE)
                return
            logger.info(
                "Produkt dopasowany: id=%s size=%s aktualny stan=%s",
                product_size.id,
                product_size.size,
                product_size.quantity,
            )

        if args.dry_run:
            logger.info(
                "[DRY-RUN] Utworzylbym zamowienie %s: sale_price=%.2f commission=%.2f "
                "tracking=%s (INPOST), status koncowy=wyslano, odjalbym 1 szt. z product_size_id=%s.",
                ORDER_ID,
                SALE_PRICE,
                COMMISSION_FEE,
                TRACKING_NUMBER,
                product_size.id,
            )
            return

        with get_session() as db:
            order = sync_order_from_data(db, ORDER_DATA)
            finalize_manual_order_creation(db, order, ORDER_DATA)
            db.commit()
            logger.info("Utworzono zamowienie %s ze statusem 'wydrukowano'.", ORDER_ID)

        # Osobna transakcja - zeby timestamp statusu "wyslano" byl pozniejszy
        # niz "wydrukowano" (func.now() jest stabilne w obrebie jednej transakcji).
        with get_session() as db:
            add_order_status(
                db,
                ORDER_ID,
                "wyslano",
                notes=(
                    "Recovery po zdropowaniu bazy 2026-07-01: etykieta drukowana "
                    "recznie (poza systemem), potwierdzone przez wlasciciela sklepu."
                ),
                send_email=False,
            )
            db.commit()
            logger.info("Ustawiono status 'wyslano' dla %s.", ORDER_ID)

        consume_order_stock(ORDER_DATA["products"], order_id=ORDER_DATA["order_id"])
        logger.info("Odjeto stan magazynowy (1 szt., product_size_id=%s).", product_size.id)

    logger.info("Gotowe.")


if __name__ == "__main__":
    main()
