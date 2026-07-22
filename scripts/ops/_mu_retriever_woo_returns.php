<?php
/**
 * Plugin Name: Retriever Woo Returns Bridge
 * Description: Most WebToffee EU Withdrawal → magazyn (webhook + REST lista).
 */
if (!defined('ABSPATH')) {
    exit;
}

/**
 * Shared secret: WP option retriever_woo_return_secret, else WOO_WEBHOOK_SECRET env,
 * else empty (webhook disabled).
 */
function rs_woo_return_secret(): string {
    $opt = (string) get_option('retriever_woo_return_secret', '');
    if ($opt !== '') {
        return $opt;
    }
    $env = (string) (getenv('WOO_WEBHOOK_SECRET') ?: '');
    return $env;
}

function rs_woo_return_magazyn_url(): string {
    $url = (string) get_option('retriever_woo_return_webhook_url', '');
    if ($url !== '') {
        return $url;
    }
    return 'https://magazyn.retrievershop.pl/webhooks/woo-return';
}

function rs_woo_return_sign(string $body): string {
    $secret = rs_woo_return_secret();
    if ($secret === '') {
        return '';
    }
    return hash_hmac('sha256', $body, $secret);
}

/**
 * Build payload from WebToffee request object / row.
 *
 * @param object|array $request Wbte_Ewb_Request or array-like.
 * @param WC_Order|null $order
 */
function rs_woo_return_build_payload($request, $order = null): array {
    $id = 0;
    $order_id = 0;
    $order_number = '';
    $email = '';
    $status = 'pending';
    $reason = '';
    $items = [];
    $created_at = gmdate('c');
    $customer_name = '';

    if (is_object($request)) {
        $id = (int) ($request->id ?? 0);
        $order_id = (int) ($request->order_id ?? 0);
        $order_number = (string) ($request->order_number ?? '');
        $email = (string) ($request->customer_email ?? '');
        $status = (string) ($request->status ?? 'pending');
        $reason = (string) ($request->reason ?? '');
        if (isset($request->created_at) && $request->created_at) {
            $created_at = is_string($request->created_at)
                ? $request->created_at
                : gmdate('c', strtotime((string) $request->created_at));
        }
        if (method_exists($request, 'get_items')) {
            $raw_items = $request->get_items();
        } elseif (isset($request->items_json)) {
            $raw_items = json_decode((string) $request->items_json, true) ?: [];
        } else {
            $raw_items = [];
        }
        if (is_array($raw_items)) {
            foreach ($raw_items as $item) {
                if (!is_array($item)) {
                    continue;
                }
                $items[] = [
                    'name' => (string) ($item['name'] ?? $item['product_name'] ?? 'Produkt'),
                    'quantity' => (int) ($item['quantity'] ?? 1),
                    'product_id' => $item['product_id'] ?? null,
                    'variation_id' => $item['variation_id'] ?? null,
                    'sku' => $item['sku'] ?? null,
                    'ean' => $item['ean'] ?? $item['barcode'] ?? null,
                    'price_brutto' => $item['price'] ?? $item['total'] ?? $item['price_brutto'] ?? null,
                    'line_item_id' => $item['item_id'] ?? $item['line_item_id'] ?? null,
                ];
            }
        }
    } elseif (is_array($request)) {
        $id = (int) ($request['id'] ?? 0);
        $order_id = (int) ($request['order_id'] ?? 0);
        $order_number = (string) ($request['order_number'] ?? '');
        $email = (string) ($request['customer_email'] ?? '');
        $status = (string) ($request['status'] ?? 'pending');
        $reason = (string) ($request['reason'] ?? '');
        $created_at = (string) ($request['created_at'] ?? $created_at);
        $decoded = json_decode((string) ($request['items_json'] ?? '[]'), true) ?: [];
        if (is_array($decoded)) {
            foreach ($decoded as $item) {
                if (!is_array($item)) {
                    continue;
                }
                $items[] = [
                    'name' => (string) ($item['name'] ?? $item['product_name'] ?? 'Produkt'),
                    'quantity' => (int) ($item['quantity'] ?? 1),
                    'product_id' => $item['product_id'] ?? null,
                    'variation_id' => $item['variation_id'] ?? null,
                    'sku' => $item['sku'] ?? null,
                    'ean' => $item['ean'] ?? $item['barcode'] ?? null,
                    'price_brutto' => $item['price'] ?? $item['total'] ?? $item['price_brutto'] ?? null,
                    'line_item_id' => $item['item_id'] ?? $item['line_item_id'] ?? null,
                ];
            }
        }
    }

    if (!$order && $order_id && function_exists('wc_get_order')) {
        $order = wc_get_order($order_id);
    }
    if ($order instanceof WC_Order) {
        if ($order_number === '') {
            $order_number = (string) $order->get_order_number();
        }
        if ($email === '') {
            $email = (string) $order->get_billing_email();
        }
        $customer_name = trim($order->get_formatted_billing_full_name());
        if ($customer_name === '') {
            $customer_name = trim($order->get_billing_first_name() . ' ' . $order->get_billing_last_name());
        }
    }

    return [
        'withdrawal_id' => $id,
        'order_id' => $order_id,
        'order_number' => $order_number,
        'customer_email' => $email,
        'customer_name' => $customer_name,
        'status' => $status,
        'reason' => $reason,
        'items' => $items,
        'created_at' => $created_at,
    ];
}

function rs_woo_return_post_to_magazyn(array $payload): void {
    $secret = rs_woo_return_secret();
    $url = rs_woo_return_magazyn_url();
    if ($secret === '' || $url === '') {
        return;
    }
    $body = wp_json_encode($payload);
    if (!is_string($body) || $body === '') {
        return;
    }
    $sig = rs_woo_return_sign($body);
    wp_remote_post($url, [
        'timeout' => 12,
        'blocking' => false,
        'headers' => [
            'Content-Type' => 'application/json',
            'X-Retriever-Signature' => $sig,
            'User-Agent' => 'retrievershop-wp-returns/1.0',
        ],
        'body' => $body,
    ]);
}

add_action('wbte_ewb_request_submitted', static function ($request, $order = null) {
    $payload = rs_woo_return_build_payload($request, $order);
    if (empty($payload['withdrawal_id']) || empty($payload['order_id'])) {
        return;
    }
    rs_woo_return_post_to_magazyn($payload);
}, 10, 2);

add_action('rest_api_init', static function () {
    register_rest_route('retrievershop/v1', '/withdrawals', [
        'methods' => 'GET',
        'permission_callback' => static function (WP_REST_Request $request) {
            $secret = rs_woo_return_secret();
            if ($secret === '') {
                return false;
            }
            $provided = (string) $request->get_header('X-Retriever-Secret');
            if ($provided === '') {
                $provided = (string) $request->get_param('secret');
            }
            return hash_equals($secret, $provided);
        },
        'callback' => static function (WP_REST_Request $request) {
            global $wpdb;
            $table = $wpdb->prefix . 'wbte_ewb_withdrawals';
            $exists = $wpdb->get_var($wpdb->prepare('SHOW TABLES LIKE %s', $table));
            if (!$exists) {
                return new WP_REST_Response(['withdrawals' => [], 'error' => 'table_missing'], 200);
            }
            $after_id = max(0, (int) $request->get_param('after_id'));
            $limit = min(100, max(1, (int) ($request->get_param('limit') ?: 50)));
            $status = (string) ($request->get_param('status') ?: '');
            $sql = "SELECT * FROM {$table} WHERE id > %d";
            $params = [$after_id];
            if ($status !== '') {
                $sql .= ' AND status = %s';
                $params[] = $status;
            }
            $sql .= ' ORDER BY id ASC LIMIT %d';
            $params[] = $limit;
            // phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared
            $rows = $wpdb->get_results($wpdb->prepare($sql, $params), ARRAY_A) ?: [];
            $out = [];
            foreach ($rows as $row) {
                $out[] = rs_woo_return_build_payload($row);
            }
            return new WP_REST_Response(['withdrawals' => $out], 200);
        },
    ]);
});
