<?php
/**
 * One-shot: create WooCommerce REST API key for magazyn.
 * Usage: wp eval-file _create_woo_api_key.php --allow-root
 */
$user_id = 1;
$description = 'magazyn-suite';
$permissions = 'read_write';
$consumer_key = 'ck_' . wc_rand_hash();
$consumer_secret = 'cs_' . wc_rand_hash();

global $wpdb;
$inserted = $wpdb->insert(
    $wpdb->prefix . 'woocommerce_api_keys',
    array(
        'user_id' => $user_id,
        'description' => $description,
        'permissions' => $permissions,
        'consumer_key' => wc_api_hash($consumer_key),
        'consumer_secret' => $consumer_secret,
        'truncated_key' => substr($consumer_key, -7),
    ),
    array('%d', '%s', '%s', '%s', '%s', '%s')
);

if (!$inserted) {
    fwrite(STDERR, "insert failed\n");
    exit(1);
}

echo $consumer_key . "\n" . $consumer_secret . "\n";
