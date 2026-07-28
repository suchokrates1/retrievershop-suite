<?php
/**
 * Plugin Name: Retriever Account Invoice PDF
 * Description: Pobieranie faktury PDF (magazyn/wFirma) na view-order.
 */
if (!defined('ABSPATH')) {
    exit;
}

function rs_invoice_magazyn_base(): string {
    $url = (string) get_option('rs_magazyn_base_url', '');
    if ($url !== '') {
        return rtrim($url, '/');
    }
    return 'https://magazyn.retrievershop.pl';
}

function rs_invoice_secret(): string {
    foreach (['rs_magazyn_mail_secret', 'retriever_woo_return_secret', 'retriever_magazyn_secret'] as $opt) {
        $v = (string) get_option($opt, '');
        if ($v !== '') {
            return $v;
        }
    }
    $env = (string) (getenv('WOO_WEBHOOK_SECRET') ?: '');
    return $env;
}

/**
 * @return array{available?:bool,invoice_number?:string}|null
 */
function rs_invoice_status(int $woo_order_id): ?array {
    $secret = rs_invoice_secret();
    if ($secret === '' || $woo_order_id < 1) {
        return null;
    }
    $url = rs_invoice_magazyn_base() . '/api/shop/orders/' . $woo_order_id . '/invoice/status';
    $res = wp_remote_get($url, [
        'timeout' => 12,
        'headers' => [
            'Authorization' => 'Bearer ' . $secret,
            'Accept' => 'application/json',
        ],
    ]);
    if (is_wp_error($res)) {
        error_log('RS_Invoice status error: ' . $res->get_error_message());
        return null;
    }
    $code = (int) wp_remote_retrieve_response_code($res);
    $body = json_decode((string) wp_remote_retrieve_body($res), true);
    if ($code !== 200 || !is_array($body)) {
        return null;
    }
    return $body;
}

function rs_invoice_user_can_access_order(WC_Order $order): bool {
    if (!is_user_logged_in()) {
        return false;
    }
    $uid = get_current_user_id();
    if ((int) $order->get_user_id() === $uid) {
        return true;
    }
    return current_user_can('manage_woocommerce') || current_user_can('edit_shop_orders');
}

add_action('woocommerce_order_details_after_order_table', static function ($order) {
    if (!$order instanceof WC_Order) {
        return;
    }
    if (!rs_invoice_user_can_access_order($order)) {
        return;
    }
    $status = rs_invoice_status((int) $order->get_id());
    if (!$status || empty($status['available'])) {
        return;
    }
    $url = wp_nonce_url(
        add_query_arg(
            [
                'rs_download_invoice' => '1',
                'order_id' => $order->get_id(),
            ],
            home_url('/')
        ),
        'rs_download_invoice_' . $order->get_id()
    );
    $label = 'Pobierz fakturę PDF';
    $nr = trim((string) ($status['invoice_number'] ?? ''));
    if ($nr !== '') {
        $label .= ' (' . $nr . ')';
    }
    echo '<p class="rs-invoice-download" style="margin:1.25rem 0 0">';
    echo '<a class="button woocommerce-button" data-rs-spa="off" href="' . esc_url($url) . '">' . esc_html($label) . '</a>';
    echo '</p>';
}, 20);

add_filter('woocommerce_my_account_my_orders_actions', static function ($actions, $order) {
    if (!$order instanceof WC_Order || !rs_invoice_user_can_access_order($order)) {
        return $actions;
    }
    // Cheap cache per-request to avoid N status calls on orders list
    static $cache = [];
    $oid = (int) $order->get_id();
    if (!array_key_exists($oid, $cache)) {
        $cache[$oid] = rs_invoice_status($oid);
    }
    $status = $cache[$oid];
    if (!$status || empty($status['available'])) {
        return $actions;
    }
    $actions['rs_invoice'] = [
        'url' => wp_nonce_url(
            add_query_arg(
                [
                    'rs_download_invoice' => '1',
                    'order_id' => $oid,
                ],
                home_url('/')
            ),
            'rs_download_invoice_' . $oid
        ),
        'name' => __('Faktura PDF', 'woocommerce'),
    ];
    return $actions;
}, 20, 2);

add_action('init', static function () {
    if (empty($_GET['rs_download_invoice']) || empty($_GET['order_id'])) { // phpcs:ignore WordPress.Security.NonceVerification
        return;
    }
    $order_id = absint($_GET['order_id']); // phpcs:ignore WordPress.Security.NonceVerification
    if ($order_id < 1) {
        wp_die('Nieprawidłowe zamówienie.', 'Faktura', ['response' => 400]);
    }
    if (!isset($_GET['_wpnonce']) || !wp_verify_nonce(sanitize_text_field(wp_unslash($_GET['_wpnonce'])), 'rs_download_invoice_' . $order_id)) {
        wp_die('Nieprawidłowy token bezpieczeństwa.', 'Faktura', ['response' => 403]);
    }
    if (!is_user_logged_in()) {
        auth_redirect();
    }
    $order = wc_get_order($order_id);
    if (!$order instanceof WC_Order || !rs_invoice_user_can_access_order($order)) {
        wp_die('Brak dostępu do tego zamówienia.', 'Faktura', ['response' => 403]);
    }

    $secret = rs_invoice_secret();
    if ($secret === '') {
        wp_die('Brak konfiguracji mostu faktur.', 'Faktura', ['response' => 500]);
    }

    $url = rs_invoice_magazyn_base() . '/api/shop/orders/' . $order_id . '/invoice.pdf';
    $res = wp_remote_get($url, [
        'timeout' => 45,
        'headers' => [
            'Authorization' => 'Bearer ' . $secret,
            'Accept' => 'application/pdf',
        ],
    ]);
    if (is_wp_error($res)) {
        error_log('RS_Invoice download error: ' . $res->get_error_message());
        wp_die('Nie udało się pobrać faktury. Spróbuj ponownie później.', 'Faktura', ['response' => 502]);
    }
    $code = (int) wp_remote_retrieve_response_code($res);
    $body = (string) wp_remote_retrieve_body($res);
    if ($code === 404) {
        wp_die('Faktura nie jest jeszcze dostępna dla tego zamówienia.', 'Faktura', ['response' => 404]);
    }
    if ($code !== 200 || strlen($body) < 100 || strncmp($body, '%PDF', 4) !== 0) {
        error_log('RS_Invoice download bad response code=' . $code . ' len=' . strlen($body));
        wp_die('Faktura chwilowo niedostępna.', 'Faktura', ['response' => 502]);
    }

    $filename = 'faktura-' . $order_id . '.pdf';
    $cd = wp_remote_retrieve_header($res, 'content-disposition');
    if (is_string($cd) && preg_match('/filename="?([^";]+)"?/i', $cd, $m)) {
        $filename = basename($m[1]);
    }

    nocache_headers();
    header('Content-Type: application/pdf');
    header('Content-Disposition: attachment; filename="' . $filename . '"');
    header('Content-Length: ' . (string) strlen($body));
    echo $body; // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped
    exit;
}, 1);
