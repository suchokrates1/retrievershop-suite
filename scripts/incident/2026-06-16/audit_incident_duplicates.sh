#!/bin/bash
set -euo pipefail
C=retrievershop-postgres
DB="psql -U magazyn -d magazyn -t -A"

echo "=== Allegro token ==="
docker exec $C $DB -c "SELECT key, length(value), updated_at FROM app_settings WHERE key LIKE 'ALLEGRO%' ORDER BY key;"

echo
echo "=== Today's orders ==="
docker exec $C psql -U magazyn -d magazyn -c "
SELECT o.order_id, o.customer_name, o.delivery_package_nr AS waybill,
       o.wfirma_invoice_number, o.wfirma_invoice_id,
       (SELECT status FROM order_status_logs WHERE order_id=o.order_id ORDER BY timestamp DESC LIMIT 1) AS last_status,
       po.printed_at IS NOT NULL AS printed
FROM orders o
LEFT JOIN printed_orders po ON po.order_id = o.order_id
WHERE o.date_add >= extract(epoch from date_trunc('day', now()))::bigint
ORDER BY o.date_add DESC;"

echo
echo "=== sm_shipment mappings ==="
docker exec $C psql -U magazyn -d magazyn -c "
SELECT key, value FROM agent_state WHERE key LIKE 'sm_shipment:%' ORDER BY key;"

echo
echo "=== Duplicate wfirma invoice numbers (today) ==="
docker exec $C psql -U magazyn -d magazyn -c "
SELECT wfirma_invoice_number, count(*), array_agg(order_id) AS orders
FROM orders
WHERE date_add >= extract(epoch from date_trunc('day', now()))::bigint
  AND wfirma_invoice_number IS NOT NULL AND wfirma_invoice_number != ''
GROUP BY wfirma_invoice_number
HAVING count(*) > 1;"

echo
echo "=== Orders with multiple status logs wydrukowano (today) ==="
docker exec $C psql -U magazyn -d magazyn -c "
SELECT order_id, count(*) AS cnt, array_agg(tracking_number) AS waybills
FROM order_status_logs
WHERE status = 'wydrukowano'
  AND timestamp >= date_trunc('day', now())
GROUP BY order_id
HAVING count(*) > 1;"

echo
echo "=== printed_orders today ==="
docker exec $C psql -U magazyn -d magazyn -c "
SELECT order_id, printed_at, last_order_data::json->>'delivery_package_nr' AS waybill
FROM printed_orders
WHERE printed_at >= date_trunc('day', now())
ORDER BY printed_at;"

echo
echo "=== label_queue ==="
docker exec $C psql -U magazyn -d magazyn -c "SELECT * FROM label_queue;"
