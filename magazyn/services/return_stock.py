"""Przywracanie stanow magazynowych po otrzymaniu zwrotu."""

from __future__ import annotations

import json
import logging
from decimal import Decimal, ROUND_HALF_UP
from typing import Callable, Dict, Optional

from ..db import TWOPLACES, get_session
from ..domain.returns import (
    RETURN_STATUS_COMPLETED,
    RETURN_STATUS_DELIVERED,
    RETURN_STATUS_IN_TRANSIT,
    RETURN_STATUS_NOT_COLLECTED,
    RETURN_STATUS_PENDING,
)
from ..models.allegro import AllegroOffer
from ..models.orders import OrderProduct
from ..models.products import ProductSize, Sale
from ..models.returns import Return, ReturnStatusLog
from ..notifications import send_messenger

logger = logging.getLogger(__name__)


def _add_return_status_log(db, return_id: int, status: str, notes: str = None) -> None:
    db.add(ReturnStatusLog(return_id=return_id, status=status, notes=notes))


def _find_product_size_for_return_item(db, return_record: Return, item: dict) -> Optional[ProductSize]:
    ean = item.get("ean")
    product_size_id = item.get("product_size_id")

    if product_size_id:
        product_size = db.query(ProductSize).filter(ProductSize.id == product_size_id).first()
        if product_size:
            return product_size

    if ean:
        product_size = db.query(ProductSize).filter(ProductSize.barcode == ean).first()
        if product_size:
            return product_size

    if not return_record.order_id:
        return None

    order_product = db.query(OrderProduct).filter(
        OrderProduct.order_id == return_record.order_id,
        OrderProduct.ean == ean,
    ).first()

    if not order_product or not order_product.auction_id:
        return None

    allegro_offer = db.query(AllegroOffer).filter(
        AllegroOffer.offer_id == order_product.auction_id,
    ).first()
    if not allegro_offer or not allegro_offer.product_size_id:
        return None

    product_size = db.query(ProductSize).filter(
        ProductSize.id == allegro_offer.product_size_id,
    ).first()
    if product_size:
        logger.info(
            "Znaleziono ProductSize przez auction_id: %s -> %s",
            order_product.auction_id,
            product_size.id,
        )
    return product_size


def _restore_stock_for_return_item(
    db,
    order_id: Optional[str],
    product_size: ProductSize,
    quantity: int,
) -> int:
    """Zwroc ``quantity`` sztuk na stan i odtworz ich wartosc (``stock_value``).

    Sztuki powiazane ze sprzedaza danego zamowienia wracaja po SWOIM koszcie
    zakupu (``Sale.purchase_cost`` z chwili sprzedazy) - dzieki temu przy
    ponownej sprzedazy zejda po tej samej cenie, a srednia magazynu nie
    zostaje zaklamana. ``Sale.quantity_returned`` chroni przed zwrotem wiekszej
    liczby sztuk niz sprzedano (czesciowe / powtorzone zwroty tego samego
    zamowienia).

    Reszta (``quantity`` minus wynik), dla ktorej nie ma danych sprzedazy
    (zamowienia sprzed wdrozenia ``order_id``, korekty reczne), wraca po
    BIEZACEJ sredniej - neutralnie dla sredniej ceny zakupu.

    Zwraca ile sztuk pokryto danymi sprzedazy.
    """
    if quantity <= 0:
        return 0

    remaining = quantity
    restored_from_sales = 0

    if order_id:
        sales = (
            db.query(Sale)
            .filter(
                Sale.order_id == order_id,
                Sale.product_id == product_size.product_id,
                Sale.size == product_size.size,
            )
            .order_by(Sale.id.asc())
            .all()
        )
        for sale in sales:
            if remaining <= 0:
                break
            sold = sale.quantity or 0
            available = sold - (sale.quantity_returned or 0)
            if available <= 0:
                continue
            take = min(available, remaining)
            unit_cost = (
                Decimal(str(sale.purchase_cost or 0)) / Decimal(sold)
                if sold
                else Decimal("0")
            )
            add_value = (unit_cost * Decimal(take)).quantize(
                TWOPLACES, rounding=ROUND_HALF_UP
            )
            product_size.quantity = (product_size.quantity or 0) + take
            product_size.stock_value = Decimal(str(product_size.stock_value or 0)) + add_value
            sale.quantity_returned = (sale.quantity_returned or 0) + take
            remaining -= take
            restored_from_sales += take

    if remaining > 0:
        avg = (
            Decimal(str(product_size.stock_value or 0)) / Decimal(product_size.quantity)
            if product_size.quantity
            else Decimal("0")
        )
        add_value = (avg * Decimal(remaining)).quantize(TWOPLACES, rounding=ROUND_HALF_UP)
        product_size.quantity = (product_size.quantity or 0) + remaining
        product_size.stock_value = Decimal(str(product_size.stock_value or 0)) + add_value

    return restored_from_sales


def restore_stock_for_return(
    return_id: int,
    *,
    accept_pending_as_delivered: bool = False,
    send_message: Callable[[str], bool] = send_messenger,
    log: Optional[logging.Logger] = None,
) -> bool:
    """Przywroc stan magazynowy dla dostarczonego zwrotu."""
    active_logger = log or logger

    with get_session() as db:
        return_record = db.query(Return).filter(Return.id == return_id).first()

        if not return_record:
            active_logger.error("Zwrot #%s nie istnieje", return_id)
            return False

        if return_record.stock_restored:
            active_logger.info("Stan dla zwrotu #%s juz zostal przywrocony", return_id)
            return True

        if accept_pending_as_delivered and return_record.status in [
            RETURN_STATUS_PENDING,
            RETURN_STATUS_IN_TRANSIT,
        ]:
            return_record.status = RETURN_STATUS_DELIVERED
            _add_return_status_log(
                db,
                return_record.id,
                RETURN_STATUS_DELIVERED,
                "Przywrocenie stanu automatycznie uznalo zwrot za odebrany",
            )

        if return_record.status not in [
            RETURN_STATUS_DELIVERED,
            RETURN_STATUS_NOT_COLLECTED,
            RETURN_STATUS_COMPLETED,
        ]:
            active_logger.warning(
                "Zwrot #%s nie jest w statusie delivered/not_collected - nie mozna przywrocic stanu",
                return_id,
            )
            return False

        try:
            items = json.loads(return_record.items_json) if return_record.items_json else []
            restored_items = []
            for item in items:
                quantity = item.get("quantity", 1)
                product_size = _find_product_size_for_return_item(db, return_record, item)

                if product_size:
                    old_qty = product_size.quantity or 0
                    restored_from_sales = _restore_stock_for_return_item(
                        db, return_record.order_id, product_size, quantity
                    )
                    restored_items.append(f"{item.get('name', 'Produkt')} +{quantity} (bylo: {old_qty})")
                    active_logger.info(
                        "Przywrocono stan: %s +%s (teraz: %s), w tym %s szt. po koszcie ze sprzedazy",
                        product_size.barcode,
                        quantity,
                        product_size.quantity,
                        restored_from_sales,
                    )
                    if restored_from_sales < quantity:
                        active_logger.info(
                            "Zwrot #%s: %s z %s szt. produktu %s bez danych sprzedazy "
                            "(brak Sale z order_id - wartosc dodana po biezacej sredniej)",
                            return_id,
                            quantity - restored_from_sales,
                            quantity,
                            product_size.barcode,
                        )
                else:
                    active_logger.warning(
                        "Nie znaleziono produktu EAN=%s, product_size_id=%s",
                        item.get("ean"),
                        item.get("product_size_id"),
                    )

            if not restored_items:
                active_logger.warning("Nie znaleziono produktow do przywrocenia dla zwrotu #%s", return_id)
                return False

            return_record.stock_restored = True
            _add_return_status_log(
                db,
                return_record.id,
                return_record.status,
                f"Przywrocono stan: {', '.join(restored_items)}",
            )
            db.commit()

            message = (
                f"[STAN PRZYWROCONY] Zamowienie {return_record.order_id}\n"
                f"Przywrocono stan: {', '.join(restored_items)}"
            )
            send_message(message)

            active_logger.info("Zakonczono obsluge zwrotu #%s", return_id)
            return True
        except Exception as exc:
            active_logger.error("Blad przywracania stanu dla zwrotu #%s: %s", return_id, exc)
            db.rollback()
            return False


def process_delivered_returns(
    *,
    restore_stock: Callable[[int], bool] = restore_stock_for_return,
    log: Optional[logging.Logger] = None,
) -> Dict[str, int]:
    """Przetworz dostarczone zwroty i przywroc stany magazynowe."""
    active_logger = log or logger
    stats = {"processed": 0, "skipped": 0, "errors": 0}

    with get_session() as db:
        delivered_returns = db.query(Return).filter(
            Return.status.in_([RETURN_STATUS_DELIVERED, RETURN_STATUS_NOT_COLLECTED]),
            Return.stock_restored.is_(False),
        ).all()

        for return_record in delivered_returns:
            try:
                if restore_stock(return_record.id):
                    stats["processed"] += 1
                else:
                    stats["skipped"] += 1
            except Exception as exc:
                active_logger.error("Blad przetwarzania zwrotu #%s: %s", return_record.id, exc)
                stats["errors"] += 1

    return stats


__all__ = ["process_delivered_returns", "restore_stock_for_return"]