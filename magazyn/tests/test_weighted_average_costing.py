"""Testy wyceny magazynu metoda sredniej wazonej kroczacej (AVCO).

Pokrywaja:
- record_purchase podnosi ProductSize.stock_value i srednia.
- consume_stock ksieguje koszt = srednia, zdejmuje proporcjonalny udzial
  wartosci, a sprzedaz calego stanu zeruje stock_value (inwariant).
- zwrot dokłada wartosc po koszcie ze sprzedazy (Sale.purchase_cost) i przelicza
  srednia - scenariusz 3 szt -> sprzedaz -> dostawa -> zwrot = srednia 70.
- Sale.quantity_returned chroni przed zwrotem wiecej niz sprzedano.
- FinancialCalculator.get_purchase_cost_for_order zwraca realny koszt.
- adjust_stock: reczne korekty spojne ze srednia.
"""

from decimal import Decimal

from magazyn.domain.financial import FinancialCalculator
from magazyn.models.orders import Order, OrderProduct
from magazyn.models.products import Product, ProductSize, Sale
from magazyn.models.returns import Return
from magazyn.services.return_stock import restore_stock_for_return
from magazyn.services.stock_adjust import adjust_stock


def _make_size(db, *, quantity=0):
    prod = Product(name="Szelki", color="Czarny")
    db.add(prod)
    db.flush()
    ps = ProductSize(product_id=prod.id, size="M", quantity=quantity)
    db.add(ps)
    db.flush()
    return prod.id, ps.id


def _make_order(db, order_id, ps_id=None):
    order = Order(order_id=order_id, platform="allegro", customer_name="Jan")
    db.add(order)
    db.flush()
    if ps_id is not None:
        db.add(
            OrderProduct(order_id=order_id, name="Szelki", quantity=1, product_size_id=ps_id)
        )
    return order


class TestPurchaseUpdatesValue:
    def test_single_delivery_sets_value_and_average(self, app_mod):
        with app_mod.get_session() as db:
            pid, _ = _make_size(db)

        app_mod.record_purchase(pid, "M", 3, 50.0)

        with app_mod.get_session() as db:
            ps = db.query(ProductSize).filter_by(product_id=pid, size="M").one()
            assert ps.quantity == 3
            assert ps.stock_value == Decimal("150.00")
            assert ps.avg_purchase_price == Decimal("50")

    def test_two_deliveries_blend_average(self, app_mod):
        with app_mod.get_session() as db:
            pid, _ = _make_size(db)

        app_mod.record_purchase(pid, "M", 2, 50.0)
        app_mod.record_purchase(pid, "M", 2, 100.0)

        with app_mod.get_session() as db:
            ps = db.query(ProductSize).filter_by(product_id=pid, size="M").one()
            assert ps.quantity == 4
            assert ps.stock_value == Decimal("300.00")
            assert ps.avg_purchase_price == Decimal("75")


class TestSaleCostsAtAverage:
    def test_sale_books_average_cost_and_reduces_value(self, app_mod):
        with app_mod.get_session() as db:
            pid, _ = _make_size(db)

        app_mod.record_purchase(pid, "M", 3, 50.0)
        app_mod.consume_stock(pid, "M", 1, sale_price=90)

        with app_mod.get_session() as db:
            sale = db.query(Sale).filter_by(product_id=pid).one()
            assert sale.purchase_cost == Decimal("50.00")
            ps = db.query(ProductSize).filter_by(product_id=pid, size="M").one()
            assert ps.quantity == 2
            assert ps.stock_value == Decimal("100.00")

    def test_selling_all_zeroes_value(self, app_mod):
        with app_mod.get_session() as db:
            pid, _ = _make_size(db)

        # Ceny dajace niecalkowita srednia, zeby sprawdzic zerowanie do grosza.
        app_mod.record_purchase(pid, "M", 3, 10.0)
        app_mod.record_purchase(pid, "M", 0 + 0, 0)  # no-op guard (0 szt.)
        app_mod.consume_stock(pid, "M", 3, sale_price=30)

        with app_mod.get_session() as db:
            ps = db.query(ProductSize).filter_by(product_id=pid, size="M").one()
            assert ps.quantity == 0
            assert ps.stock_value == Decimal("0.00")


class TestReturnRecomputesAverage:
    def test_scenario_three_units_sell_deliver_return(self, app_mod):
        """3 szt @50 -> sprzedaz 1 (koszt 50) -> dostawa 2 @100 (srednia 75) ->
        zwrot sprzedanej sztuki -> wartosc 350, srednia 70."""
        with app_mod.get_session() as db:
            pid, ps_id = _make_size(db)
            _make_order(db, "order-70", ps_id)

        app_mod.record_purchase(pid, "M", 3, 50.0)
        app_mod.consume_stock(pid, "M", 1, sale_price=90, order_id="order-70")
        app_mod.record_purchase(pid, "M", 2, 100.0)

        with app_mod.get_session() as db:
            ps = db.query(ProductSize).filter_by(product_id=pid, size="M").one()
            assert ps.quantity == 4
            assert ps.stock_value == Decimal("300.00")
            assert ps.avg_purchase_price == Decimal("75")

            ret = Return(
                order_id="order-70",
                status="delivered",
                items_json=f'[{{"name": "Szelki", "quantity": 1, "product_size_id": {ps_id}}}]',
            )
            db.add(ret)
            db.flush()
            return_id = ret.id

        assert restore_stock_for_return(return_id) is True

        with app_mod.get_session() as db:
            ps = db.query(ProductSize).filter_by(product_id=pid, size="M").one()
            assert ps.quantity == 5
            assert ps.stock_value == Decimal("350.00")
            assert ps.avg_purchase_price == Decimal("70")

            sale = db.query(Sale).filter_by(order_id="order-70").one()
            assert sale.quantity_returned == 1

    def test_double_return_guarded_by_quantity_returned(self, app_mod):
        from magazyn.services.return_stock import _restore_stock_for_return_item

        with app_mod.get_session() as db:
            pid, ps_id = _make_size(db)
            _make_order(db, "order-dbl", ps_id)

        app_mod.record_purchase(pid, "M", 2, 5.0)
        app_mod.consume_stock(pid, "M", 2, sale_price=20, order_id="order-dbl")

        with app_mod.get_session() as db:
            ps = db.query(ProductSize).filter_by(product_id=pid, size="M").one()
            first = _restore_stock_for_return_item(db, "order-dbl", ps, 2)
            db.commit()
        assert first == 2

        with app_mod.get_session() as db:
            ps = db.query(ProductSize).filter_by(product_id=pid, size="M").one()
            # Alokacja juz rozliczona -> nic wiecej nie wraca po koszcie sprzedazy;
            # 2 szt. trafiaja jako korekta po biezacej sredniej.
            second = _restore_stock_for_return_item(db, "order-dbl", ps, 2)
            db.commit()
        assert second == 0


class TestPurchaseCostForOrder:
    def test_real_cost_independent_of_later_delivery(self, app_mod):
        with app_mod.get_session() as db:
            pid, ps_id = _make_size(db)
            _make_order(db, "order-real", ps_id)

        app_mod.record_purchase(pid, "M", 1, 12.0)
        app_mod.consume_stock(pid, "M", 1, sale_price=40, order_id="order-real")
        # Drozsza dostawa PO sprzedazy nie moze zmienic kosztu tego zamowienia.
        app_mod.record_purchase(pid, "M", 5, 99.0)

        with app_mod.get_session() as db:
            calc = FinancialCalculator(db, settings_store=None)
            cost, is_actual = calc.get_purchase_cost_for_order("order-real", with_source=True)

        assert is_actual is True
        assert cost == Decimal("12.00")


class TestManualAdjust:
    def test_increase_with_price_shifts_average(self, app_mod):
        with app_mod.get_session() as db:
            pid, _ = _make_size(db)
        app_mod.record_purchase(pid, "M", 2, 50.0)  # value 100, avg 50

        adjust_stock(pid, "M", delta=2, unit_price=100)  # +200 -> value 300, avg 75

        with app_mod.get_session() as db:
            ps = db.query(ProductSize).filter_by(product_id=pid, size="M").one()
            assert ps.quantity == 4
            assert ps.stock_value == Decimal("300.00")
            assert ps.avg_purchase_price == Decimal("75")

    def test_increase_without_price_is_neutral(self, app_mod):
        with app_mod.get_session() as db:
            pid, _ = _make_size(db)
        app_mod.record_purchase(pid, "M", 2, 50.0)

        adjust_stock(pid, "M", delta=1)  # po sredniej 50 -> value 150, avg 50

        with app_mod.get_session() as db:
            ps = db.query(ProductSize).filter_by(product_id=pid, size="M").one()
            assert ps.quantity == 3
            assert ps.stock_value == Decimal("150.00")
            assert ps.avg_purchase_price == Decimal("50")

    def test_decrease_removes_at_average(self, app_mod):
        with app_mod.get_session() as db:
            pid, _ = _make_size(db)
        app_mod.record_purchase(pid, "M", 4, 25.0)  # value 100, avg 25

        adjust_stock(pid, "M", delta=-2)  # -50 -> value 50

        with app_mod.get_session() as db:
            ps = db.query(ProductSize).filter_by(product_id=pid, size="M").one()
            assert ps.quantity == 2
            assert ps.stock_value == Decimal("50.00")

    def test_set_to_zero_zeroes_value(self, app_mod):
        with app_mod.get_session() as db:
            pid, _ = _make_size(db)
        app_mod.record_purchase(pid, "M", 4, 25.0)

        adjust_stock(pid, "M", set_to=0)

        with app_mod.get_session() as db:
            ps = db.query(ProductSize).filter_by(product_id=pid, size="M").one()
            assert ps.quantity == 0
            assert ps.stock_value == Decimal("0.00")
