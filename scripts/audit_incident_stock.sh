#!/bin/bash
C=retrievershop-postgres

echo "=== Sales on 2026-06-16 (incident window 22:00+) ==="
docker exec $C psql -U magazyn -d magazyn -c "
SELECT s.id, s.sale_date, p.name, p.color, s.size, s.quantity, s.sale_price
FROM sales s
JOIN products p ON p.id = s.product_id
WHERE s.sale_date >= '2026-06-16 22:00:00'
ORDER BY s.sale_date;"

echo
echo "=== All sales on 2026-06-16 ==="
docker exec $C psql -U magazyn -d magazyn -c "
SELECT count(*), min(sale_date), max(sale_date)
FROM sales WHERE sale_date::date = '2026-06-16';"

echo
echo "=== Duplicate sales same day for incident order products (by name+size) ==="
docker exec $C psql -U magazyn -d magazyn -c "
SELECT p.name, s.size, count(*) AS cnt, array_agg(s.sale_date ORDER BY s.sale_date) AS dates
FROM sales s
JOIN products p ON p.id = s.product_id
WHERE s.sale_date::date >= '2026-06-14'
GROUP BY p.name, s.size
HAVING count(*) > 1
ORDER BY cnt DESC
LIMIT 20;"

echo
echo "=== Unknown product sales on 2026-06-16 ==="
docker exec $C psql -U magazyn -d magazyn -c "
SELECT s.id, s.sale_date, s.size, s.quantity
FROM sales s
JOIN products p ON p.id = s.product_id
WHERE p.name = 'Unknown' AND s.sale_date::date = '2026-06-16'
ORDER BY s.sale_date;"

echo
echo "=== product_id=45 Uniwersalny sales around incident ==="
docker exec $C psql -U magazyn -d magazyn -c "
SELECT s.id, s.sale_date, s.quantity, s.sale_price
FROM sales s
WHERE s.product_id = 45 AND s.size = 'Uniwersalny'
  AND s.sale_date >= '2026-06-14'
ORDER BY s.sale_date;"

echo
echo "=== Latest sales in DB ==="
docker exec $C psql -U magazyn -d magazyn -c "
SELECT max(sale_date) AS last_sale, count(*) AS total FROM sales;"
