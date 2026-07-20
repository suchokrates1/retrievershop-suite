<?php
/**
 * Create WooCommerce webhooks pointing at magazyn.
 * Usage: wp eval-file _create_woo_webhooks.php --allow-root
 * Env: WOO_WEBHOOK_SECRET, WOO_WEBHOOK_URL
 */
$secret = getenv('WOO_WEBHOOK_SECRET') ?: '';
$url = getenv('WOO_WEBHOOK_URL') ?: 'https://magazyn.retrievershop.pl/webhooks/woocommerce';
if (!$secret) {
    fwrite(STDERR, "WOO_WEBHOOK_SECRET missing\n");
    exit(1);
}

$topics = array('order.created', 'order.updated');
foreach ($topics as $topic) {
    $existing = get_posts(
        array(
            'post_type' => 'shop_webhook',
            'post_status' => 'any',
            'numberposts' => -1,
            'meta_key' => '_topic',
            'meta_value' => $topic,
        )
    );
    $skip = false;
    foreach ($existing as $post) {
        $delivery = get_post_meta($post->ID, '_delivery_url', true);
        if ($delivery === $url) {
            echo "exists topic={$topic} id={$post->ID}\n";
            $skip = true;
            break;
        }
    }
    if ($skip) {
        continue;
    }

    $webhook = new WC_Webhook();
    $webhook->set_name('Magazyn ' . $topic);
    $webhook->set_user_id(1);
    $webhook->set_topic($topic);
    $webhook->set_delivery_url($url);
    $webhook->set_secret($secret);
    $webhook->set_status('active');
    $webhook->save();
    echo "created topic={$topic} id=" . $webhook->get_id() . "\n";
}
