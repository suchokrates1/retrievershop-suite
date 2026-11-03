<?php
/**
 * E2E: create Woo order → print sync hint → guest withdrawal → webhook.
 * Keeps order until --cleanup. Pair with magazyn import.
 *
 * Steps:
 *   1) php /tmp/_e2e_ewb_with_magazyn.php create
 *   2) sync order on magazyn (import woo_<id>)
 *   3) php /tmp/_e2e_ewb_with_magazyn.php withdraw
 *   4) php /tmp/_e2e_ewb_with_magazyn.php cleanup
 */
require_once '/var/www/html/wp-load.php';

$cmd = $argv[1] ?? 'create';
$test_email = getenv('E2E_EMAIL') ?: 'dawsuchodolski@gmail.com';
$marker = '_rs_ewb_e2e_test';
$state_file = '/tmp/rs_ewb_e2e_state.json';

function rs_log($m) { echo $m . "\n"; }

function rs_state_load($f) {
    if (!file_exists($f)) return [];
    return json_decode(file_get_contents($f), true) ?: [];
}
function rs_state_save($f, $s) {
    file_put_contents($f, wp_json_encode($s));
}

if ($cmd === 'cleanup') {
    global $wpdb;
    $state = rs_state_load($state_file);
    $oid = (int) ($state['order_id'] ?? 0);
    if ($oid) {
        $o = wc_get_order($oid);
        if ($o) { $o->delete(true); rs_log("deleted order $oid"); }
    }
    foreach (['wbte_ewb_pending_withdrawals', 'wbte_ewb_withdrawals'] as $t) {
        $table = $wpdb->prefix . $t;
        if ($wpdb->get_var($wpdb->prepare('SHOW TABLES LIKE %s', $table))) {
            $n = $wpdb->query("DELETE FROM `$table` WHERE reason LIKE '%[RS-E2E]%'");
            rs_log("cleanup $table=$n");
        }
    }
    @unlink($state_file);
    exit(0);
}

if ($cmd === 'create') {
    $settings = get_option('wbte_ewb_settings');
    if (!is_array($settings)) $settings = [];
    $settings['withdrawal_period'] = 14;
    $settings['withdrawal_period_start_statuses'] = ['wc-completed'];
    $settings['reason_required'] = 'yes';
    update_option('wbte_ewb_settings', $settings, false);

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
    if (!$product_id) { fwrite(STDERR, "no product\n"); exit(2); }

    $order = wc_create_order();
    $order->set_billing_email($test_email);
    $order->set_billing_first_name('E2E');
    $order->set_billing_last_name('Bridge');
    $order->set_payment_method('cod');
    $order->set_payment_method_title('E2E COD');
    $order->add_product(wc_get_product($product_id), 1);
    $order->calculate_totals();
    $order->update_meta_data($marker, '1');
    $order->update_status('completed', 'E2E bridge test');
    $order->save();

    $state = [
        'order_id' => $order->get_id(),
        'order_number' => $order->get_order_number(),
        'email' => $test_email,
        'product_id' => $product_id,
        'total' => $order->get_total(),
    ];
    rs_state_save($state_file, $state);
    rs_log('CREATED ' . wp_json_encode($state));
    exit(0);
}

if ($cmd === 'withdraw') {
    $state = rs_state_load($state_file);
    $order_id = (int) ($state['order_id'] ?? 0);
    $order = wc_get_order($order_id);
    if (!$order) { fwrite(STDERR, "order missing\n"); exit(3); }

    $mail_error = null;
    $mails = [];
    add_action('wp_mail_failed', function ($e) use (&$mail_error) { $mail_error = $e->get_error_message(); });
    add_filter('wp_mail', function ($args) use (&$mails) {
        $mails[] = ['to' => $args['to'] ?? '', 'subject' => $args['subject'] ?? ''];
        return $args;
    });

    $guest = wbte_ewb()->get('guest_withdrawal');
    $queue = $guest->queue_request([
        'order_number' => (string) $order->get_order_number(),
        'email' => $state['email'],
        'reason' => '[RS-E2E] bridge SMTP queue',
    ]);
    rs_log('queue_ok=' . (!is_wp_error($queue) && $queue ? 'yes' : 'no'));
    rs_log('mail_error=' . var_export($mail_error, true));
    rs_log('mails=' . wp_json_encode($mails, JSON_UNESCAPED_UNICODE));

    global $wpdb;
    $pending = $wpdb->get_row("SELECT * FROM {$wpdb->prefix}wbte_ewb_pending_withdrawals ORDER BY id DESC LIMIT 1", ARRAY_A);
    $token = $pending['verify_token'] ?? '';
    if ($token === '') { fwrite(STDERR, "no token\n"); exit(4); }

    $verify = $guest->verify_email($token);
    rs_log('verify_ok=' . (!is_wp_error($verify) ? 'yes' : 'no'));

    $items = [];
    foreach ($order->get_items() as $item_id => $item) {
        $items[] = ['item_id' => $item_id, 'quantity' => (int) $item->get_quantity()];
    }
    $submit = $guest->submit_verified_request($token, [
        'items' => $items,
        'reason' => '[RS-E2E] bridge submit',
        'request_type' => 'full',
    ]);
    rs_log('submit_ok=' . (!is_wp_error($submit) ? 'yes' : 'no'));

    $wrow = $wpdb->get_row("SELECT * FROM {$wpdb->prefix}wbte_ewb_withdrawals ORDER BY id DESC LIMIT 1", ARRAY_A);
    rs_log('withdrawal_id=' . ($wrow['id'] ?? 'none'));

    $webhook = null;
    if ($wrow && function_exists('rs_woo_return_post_to_magazyn')) {
        $payload = rs_woo_return_build_payload($wrow, $order);
        $webhook = rs_woo_return_post_to_magazyn($payload);
    }
    rs_log('magazyn_webhook=' . wp_json_encode($webhook, JSON_UNESCAPED_UNICODE));
    $state['withdrawal_id'] = $wrow['id'] ?? null;
    $state['webhook'] = $webhook;
    rs_state_save($state_file, $state);

    $ok = !is_wp_error($queue) && !is_wp_error($verify) && !is_wp_error($submit)
        && is_array($webhook) && !empty($webhook['ok']);
    rs_log('BRIDGE_OK=' . ($ok ? 'yes' : 'no'));
    exit($ok ? 0 : 10);
}

fwrite(STDERR, "usage: create|withdraw|cleanup\n");
exit(1);
