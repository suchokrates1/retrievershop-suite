"""Minimal TipTop/Shoper product page fixture for unit tests."""

TIPTOP_ACTIVE_COLLAR_HTML = """
<!DOCTYPE html>
<html lang="pl">
<head>
  <title>Obroża dla psa Truelove Active – tiptop24.pl</title>
  <meta itemprop="price" content="59.00">
</head>
<body>
  <h1 class="product_name">Obroża dla psa Truelove Active</h1>
  <div data-product-id="214" data-producer="Truelove"></div>
  <script>
    Shop.values.OptionCurrentStock = "214";
  </script>
  <form class="form-basket">
    <input type="hidden" value="214" name="stock_id">
    <label for="option_8">Rozmiar:</label>
    <select id="option_8" name="option_8">
      <option value="48">XS</option>
      <option value="49">S</option>
      <option value="50">M</option>
      <option value="51">L</option>
      <option value="52">XL</option>
    </select>
    <label for="option_9">kolor:</label>
    <select id="option_9" name="option_9" class="gc__color">
      <option value="">wybierz</option>
      <option value="56">limonkowy</option>
      <option value="60">czarny</option>
      <option value="161">czerwony</option>
    </select>
  </form>
  <p>Producent: <a href="#">Truelove</a></p>
</body>
</html>
"""

TIPTOP_LISTING_HTML = """
<html>
<body>
  <a href="/dla-psa/obroza-dla-psa-truelove-active" class="product__name">Obroża Active</a>
  <a href="/dla-psa/szelki-dla-psa-truelove-front-line-premium">Front Line</a>
  <a href="/pl/s?search=Truelove">search</a>
  <a href="/basket">koszyk</a>
</body>
</html>
"""
