<?php
/**
 * E2E WebToffee withdrawal with real SMTP mail.
 *
 * Usage:
 *   docker exec -e E2E_EMAIL=dawsuchodolski@gmail.com retrievershop-wp php /tmp/_e2e_ewb_return_flow.php
 *   docker exec retrievershop-wp php /tmp/_e2e_ewb_return_flow.php --cleanup-only
 */
require_once '/var/www/html/wp-load.php';

if (!function_exists('wbte_ewb') || !function_exists('wc_create_order')) {
    fwrite(STDERR, "Woo / WebToffee not available\n");
    exit(1);
}

$cleanup_only = in_array('--cleanup-only', $argv ?? [], true);
$test_email = getenv('E2E_EMAIL') ?: 'dawsuchodolski@gmail.com';
$marker = '_rs_ewb_e2e_test';

function rs_e2e_log(string $msg): void {
    echo $msg . "\n";
}

function rs_e2e_cleanup(): void {
    global $wpdb, $marker;
    $order_ids = $wpdb->get_col(
        $wpdb->prepare(
            "SELECT post_id FROM {$wpdb->postmeta} WHERE meta_key=%s AND meta_value=%s",
            $marker,
            '1'
        )
    );
    $order_ids = array_merge(
        $order_ids,
        $wpdb->get_col(
            $wpdb->prepare(
                "SELECT order_id FROM {$wpdb->prefix}wc_orders_meta WHERE meta_key=%s AND meta_value=%s",
                $marker,
                '1'
            )
        )
    );
    $order_ids = array_unique(array_map('intval', $order_ids));
    foreach ($order_ids as $oid) {
        $order = wc_get_order($oid);
        if ($order) {
            $order->delete(true);
            rs_e2e_log("cleanup order $oid");
        }
    }
    foreach (['wbte_ewb_pending_withdrawals', 'wbte_ewb_withdrawals'] as $t) {
        $table = $wpdb->prefix . $t;
        if (!$wpdb->get_var($wpdb->prepare('SHOW TABLES LIKE %s', $table))) {
            continue;
        }
        $n = $wpdb->query("DELETE FROM `$table` WHERE reason LIKE '%[RS-E2E]%'");
        rs_e2e_log("cleanup $table rows=" . (int) $n);
    }
}

if ($cleanup_only) {
    rs_e2e_cleanup();
    exit(0);
}

rs_e2e_log('=== E2E WebToffee + SMTP ===');
rs_e2e_log('smtp_configured=' . (function_exists('rs_smtp_is_configured') && rs_smtp_is_configured() ? 'yes' : 'no'));
rs_e2e_log('site_mailer_active=' . (is_plugin_active('site-mailer/site-mailer.php') ? 'YES' : 'no'));
rs_e2e_log('test_email=' . $test_email);

$settings = get_option('wbte_ewb_settings');
if (!is_array($settings)) {
    $settings = [];
}
$settings['withdrawal_period'] = 14;
$settings['withdrawal_period_start_statuses'] = ['wc-completed'];
$settings['reason_required'] = 'yes';
$settings['allow_partial_withdrawals'] = 'yes';
update_option('wbte_ewb_settings', $settings, false);

// Pick purchasable simple product
$product_id = 0;
$q = new WP_Query([
    'post_type' => 'product',
    'post_status' => 'publish',
    'posts_per_page' => 30,
    'orderby' => 'meta_value_num',
    'meta_key' => '_price',
    'order' => 'ASC',
    'tax_query' => [[
        'taxonomy' => 'product_type',
        'field' => 'slug',
        'terms' => ['simple'],
    ]],
]);
foreach ($q->posts as $p) {
    $prod = wc_get_product($p->ID);
    if ($prod && $prod->is_purchasable()) {
        $product_id = (int) $p->ID;
        break;
    }
}
wp_reset_postdata();
if (!$product_id) {
    $ids = wc_get_products(['status' => 'publish', 'limit' => 5, 'return' => 'ids']);
    $product_id = (int) ($ids[0] ?? 0);
}
if (!$product_id) {
    fwrite(STDERR, "No product\n");
    exit(2);
}
rs_e2e_log("product_id=$product_id");

$order = wc_create_order();
$order->set_billing_email($test_email);
$order->set_billing_first_name('E2E');
$order->set_billing_last_name('SMTP');
$order->set_payment_method('cod');
$order->set_payment_method_title('E2E COD');
$order->add_product(wc_get_product($product_id), 1);
$order->calculate_totals();
$order->update_meta_data($marker, '1');
$order->update_status('completed', 'E2E sandbox withdrawal+SMTP');
$order->save();
$order_id = $order->get_id();
$order_number = $order->get_order_number();
rs_e2e_log("order_id=$order_id number=$order_number");

$elig = wbte_ewb()->get('eligibility');
$eligible = $elig->is_order_eligible($order);
rs_e2e_log('eligible=' . var_export($eligible, true));
if (!$eligible) {
    rs_e2e_cleanup();
    exit(3);
}

$mail_error = null;
$mail_subjects = [];
add_action('wp_mail_failed', static function ($e) use (&$mail_error) {
    $mail_error = $e->get_error_message();
}, 10, 1);
add_filter('wp_mail', static function ($args) use (&$mail_subjects) {
    $mail_subjects[] = [
        'to' => $args['to'] ?? '',
        'subject' => $args['subject'] ?? '',
    ];
    return $args;
}, 5);

$guest = wbte_ewb()->get('guest_withdrawal');
$queue = $guest->queue_request([
    'order_number' => (string) $order_number,
    'email' => $test_email,
    'reason' => '[RS-E2E] sandbox guest queue via SMTP',
]);
rs_e2e_log('queue_ok=' . (!is_wp_error($queue) && $queue ? 'yes' : 'no'));
if (is_wp_error($queue)) {
    rs_e2e_log('queue_error=' . $queue->get_error_code() . ':' . $queue->get_error_message());
}
rs_e2e_log('mail_error=' . var_export($mail_error, true));
rs_e2e_log('mails=' . wp_json_encode($mail_subjects, JSON_UNESCAPED_UNICODE));

global $wpdb;
$pending_table = $wpdb->prefix . 'wbte_ewb_pending_withdrawals';
$pending = $wpdb->get_row("SELECT * FROM `$pending_table` ORDER BY id DESC LIMIT 1", ARRAY_A);
rs_e2e_log('pending=' . wp_json_encode($pending, JSON_UNESCAPED_UNICODE));
$token = $pending['verify_token'] ?? null;
if (!$token) {
    rs_e2e_log('FAIL: no verify token');
    rs_e2e_cleanup();
    exit(4);
}

$verify = $guest->verify_email($token);
rs_e2e_log('verify_ok=' . (!is_wp_error($verify) ? 'yes' : 'no'));
if (is_wp_error($verify)) {
    rs_e2e_log('verify_error=' . $verify->get_error_message());
    rs_e2e_cleanup();
    exit(5);
}

$line_items = [];
foreach ($order->get_items() as $item_id => $item) {
    $line_items[] = [
        'item_id' => $item_id,
        'quantity' => (int) $item->get_quantity(),
    ];
}
$submit = $guest->submit_verified_request($token, [
    'items' => $line_items,
    'reason' => '[RS-E2E] full withdrawal after SMTP verify',
    'request_type' => 'full',
]);
rs_e2e_log('submit_ok=' . (!is_wp_error($submit) ? 'yes' : 'no'));
if (is_wp_error($submit)) {
    rs_e2e_log('submit_error=' . $submit->get_error_code() . ':' . $submit->get_error_message());
}

$wtable = $wpdb->prefix . 'wbte_ewb_withdrawals';
$wrow = $wpdb->get_row("SELECT * FROM `$wtable` ORDER BY id DESC LIMIT 1", ARRAY_A);
rs_e2e_log('withdrawal=' . wp_json_encode($wrow, JSON_UNESCAPED_UNICODE));

$webhook = null;
if ($wrow && function_exists('rs_woo_return_build_payload') && function_exists('rs_woo_return_post_to_magazyn')) {
    $payload = rs_woo_return_build_payload($wrow, $order);
    $webhook = rs_woo_return_post_to_magazyn($payload);
    rs_e2e_log('magazyn_webhook=' . substr(wp_json_encode($webhook, JSON_UNESCAPED_UNICODE), 0, 1000));
}

// Frontend page probe
$front = wp_remote_get(home_url('/wniosek-o-odstapienie/'), ['timeout' => 20, 'sslverify' => false]);
$code = is_wp_error($front) ? 0 : wp_remote_retrieve_response_code($front);
$body = is_wp_error($front) ? '' : wp_remote_retrieve_body($front);
rs_e2e_log('page_http=' . $code);
rs_e2e_log('page_has_form=' . (strpos($body, 'wbte-ewb-withdrawal-form') !== false ? 'yes' : 'no'));
rs_e2e_log('page_js_lazy=' . (strpos($body, 'type="o/js-lzl"') !== false ? 'yes' : 'no'));

$created_order_id = $order_id;
rs_e2e_log('=== CLEANUP Woo side ===');
rs_e2e_cleanup();

rs_e2e_log('=== SUMMARY ===');
$mail_ok = $mail_error === null && !empty($mail_subjects);
$flow_ok = $eligible && $token && !is_wp_error($verify) && !is_wp_error($submit) && !empty($wrow);
rs_e2e_log('smtp_mail_ok=' . ($mail_ok ? 'yes' : 'no'));
rs_e2e_log('withdrawal_flow_ok=' . ($flow_ok ? 'yes' : 'no'));
rs_e2e_log('created_order_id=' . $created_order_id);
rs_e2e_log('NOTE: magazyn may return order_not_found until Woo sync; mail+WebToffee path is the critical guest UX.');

if (!$mail_ok || !$flow_ok) {
    exit(10);
}
