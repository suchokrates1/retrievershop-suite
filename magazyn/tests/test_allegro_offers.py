from decimal import Decimal
import re

from magazyn.db import get_session
from magazyn.models import AllegroOffer, Product, ProductSize


def test_offers_page_shows_manual_mapping_dropdown(client, login):
    with get_session() as session:
        product = Product(name="Szelki spacerowe", color="Czerwone")
        session.add(product)
        session.flush()
        size = ProductSize(
            product_id=product.id,
            size="M",
            quantity=5,
            barcode="1234567890123",
        )
        session.add(size)
        session.flush()
        session.add(
            AllegroOffer(
                offer_id="offer-1",
                title="Szelki na spacery",
                price=Decimal("129.99"),
                product_id=product.id,
                product_size_id=size.id,
            )
        )

    response = client.get("/allegro/offers")

    body = response.data.decode("utf-8")
    assert "data-search-input" in body
    assert "Brak powiązania" in body
    assert "Szelki spacerowe" in body
    assert "EAN: 1234567890123" in body


def test_link_offer_to_product_size_updates_relation(client, login):
    with get_session() as session:
        product_current = Product(name="Smycz stara")
        product_target = Product(name="Smycz nowa", color="Granatowa")
        session.add_all([product_current, product_target])
        session.flush()

        size_target = ProductSize(
            product_id=product_target.id,
            size="L",
            quantity=3,
            barcode="ABC123",
        )
        session.add(size_target)
        session.flush()

        offer_id = "offer-2"
        session.add(
            AllegroOffer(
                offer_id=offer_id,
                title="Oferta Smyczy",
                price=Decimal("59.99"),
                product_id=product_current.id,
            )
        )

    response = client.post(
        f"/allegro/link/{offer_id}",
        data={"product_size_id": size_target.id},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/allegro/offers")

    with get_session() as session:
        updated = (
            session.query(AllegroOffer)
            .filter(AllegroOffer.offer_id == offer_id)
            .one()
        )
        assert updated.product_size_id == size_target.id
        assert updated.product_id == product_target.id


def test_offers_without_inventory_are_listed_first(client, login):
    with get_session() as session:
        product_a = Product(name="Produkt A")
        product_b = Product(name="Produkt B")
        session.add_all([product_a, product_b])
        session.flush()

        size_a = ProductSize(product_id=product_a.id, size="S")
        size_b = ProductSize(product_id=product_b.id, size="M")
        session.add_all([size_a, size_b])
        session.flush()

        session.add_all(
            [
                AllegroOffer(
                    offer_id="offer-unlinked",
                    title="ZZZ Oferta bez przypisania",
                    price=Decimal("10.00"),
                ),
                AllegroOffer(
                    offer_id="offer-alpha",
                    title="AAA Oferta powiązana",
                    price=Decimal("20.00"),
                    product_size_id=size_a.id,
                    product_id=product_a.id,
                ),
                AllegroOffer(
                    offer_id="offer-omega",
                    title="OOO Oferta powiązana",
                    price=Decimal("30.00"),
                    product_size_id=size_b.id,
                    product_id=product_b.id,
                ),
            ]
        )

    response = client.get("/allegro/offers")
    body = response.data.decode("utf-8")

    table_match = re.search(r"<tbody>(.*?)</tbody>", body, re.S)
    assert table_match, "Expected offers table body in the response"
    rows = re.findall(r"<tr>(.*?)</tr>", table_match.group(1), re.S)

    titles = []
    for row in rows:
        columns = re.findall(r"<td>(.*?)</td>", row, re.S)
        if len(columns) >= 2:
            titles.append(re.sub(r"\s+", " ", columns[1]).strip())

    assert titles[0] == "ZZZ Oferta bez przypisania"
    assert titles[1:] == sorted(titles[1:])
