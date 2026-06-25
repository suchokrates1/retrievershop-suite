"""Testy prototypu HTTP SSR dla cen konkurencji."""

from magazyn.services.allegro_price_scraper.http_offers import (
    cheapest_gross_from_snapshot,
    parse_offer_page_html,
)


SAMPLE_HTML = """
<script>{"title":"Ten produkt od innych sprzedających","productName":"Test","offerCount":7,"links":[
{"title":"NAJTANIEJ","links":[{"selector":"other-offers-link-cheapest","subtitle":"Stan: Nowy",
"rawPrice":{"amount":"219.99","currency":"PLN","label":"netto"},
"secondaryPrice":{"main":"219,","fraction":"99 zł","label":"bez VAT"}}]},
{"title":"NAJSZYBCIEJ","links":[{"selector":"other-offers-link-fastest","subtitle":"dostawa jutro",
"rawPrice":{"amount":"187.80","currency":"PLN","label":"netto"},
"secondaryPrice":{"main":"231,","fraction":"00 zł","label":"z 23% VAT"}}]}
]}</script>
"""


def test_parse_offer_page_html_extracts_gross_from_secondary_vat():
    snapshot = parse_offer_page_html("18675226204", SAMPLE_HTML)
    assert snapshot is not None
    assert snapshot.offer_count == 7
    assert len(snapshot.summaries) == 2

    fastest = snapshot.summaries[1]
    assert fastest.net_price == 187.80
    assert fastest.gross_price == 231.0

    # Sprzedawca "bez VAT" (zwolniony) -> brutto == netto, BEZ doliczania 23%.
    cheapest = snapshot.summaries[0]
    assert cheapest.gross_price == 219.99
    # Najtanszy brutto z podsumowania = min(219.99, 231.00).
    assert cheapest_gross_from_snapshot(snapshot) == 219.99
