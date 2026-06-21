#!/bin/bash
C=retrievershop-postgres

echo "=== Maria order ==="
docker exec $C psql -U magazyn -d magazyn -c "
SELECT order_id, customer_name, delivery_package_nr, wfirma_invoice_number,
       to_timestamp(date_add) AS order_dt
FROM orders
WHERE order_id LIKE '%b94d1a60%' OR customer_name ILIKE '%Leśniak%';"

echo
echo "=== Sales kamizelka (recent) ==="
docker exec $C psql -U magazyn -d magazyn -c "
SELECT s.id, s.sale_date, p.name, p.color, s.size, s.quantity, s.sale_price
FROM sales s
JOIN products p ON p.id = s.product_id
WHERE p.name ILIKE '%kamizelka%' OR p.name ILIKE '%chłodz%'
ORDER BY s.sale_date DESC
LIMIT 15;"

echo
echo "=== Sales 2026-06-15 and 2026-06-16 ==="
docker exec $C psql -U magazyn -d magazyn -c "
SELECT s.id, s.sale_date, p.name, p.color, s.size, s.quantity, s.sale_price
FROM sales s
JOIN products p ON p.id = s.product_id
WHERE s.sale_date::date IN ('2026-06-15', '2026-06-16')
ORDER BY s.sale_date;"

echo
echo "=== Product kamizelka M zółta stock ==="
docker exec $C psql -U magazyn -d magazyn -c "
SELECT p.id, p.name, p.color, ps.size, ps.quantity, ps.barcode
FROM products p
JOIN product_sizes ps ON ps.product_id = p.id
WHERE p.name ILIKE '%kamizelka%' AND p.color ILIKE '%ółt%'
ORDER BY ps.size;"

echo
echo "=== Unknown sales 15-16 Jun ==="
docker exec $C psql -U magazyn -d magazyn -c "
SELECT s.id, s.sale_date, s.size, s.quantity, s.sale_price
FROM sales s
JOIN products p ON p.id = s.product_id
WHERE p.name = 'Unknown'
  AND s.sale_date::date >= '2026-06-15'
ORDER BY s.sale_date;"

echo
echo "=== printed_orders Maria ==="
docker exec $C psql -U magazyn -d magazyn -c "
SELECT order_id, printed_at, left(last_order_data, 120) AS data_preview
FROM printed_orders
WHERE order_id LIKE '%b94d1a60%';"
