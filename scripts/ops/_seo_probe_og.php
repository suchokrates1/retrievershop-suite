<?php
require '/var/www/html/wp-load.php';
header('Content-Type: text/plain; charset=utf-8');
global $wpdb;
$rows = $wpdb->get_results(
    "SELECT post_id, og_image_type, LEFT(og_image_url,140) u, LEFT(og_image_custom_url,100) c
     FROM {$wpdb->prefix}aioseo_posts
     WHERE og_image_url LIKE '%fbcdn%' OR og_image_custom_url LIKE '%fbcdn%'
        OR og_image_url LIKE '%facebook%' OR og_image_custom_url LIKE '%facebook%'
     LIMIT 25"
);
foreach ($rows as $r) {
    echo "#{$r->post_id} type={$r->og_image_type} url={$r->u} custom={$r->c}\n";
}
echo 'fbcdn_count=' . $wpdb->get_var(
    "SELECT COUNT(*) FROM {$wpdb->prefix}aioseo_posts
     WHERE og_image_url LIKE '%fbcdn%' OR og_image_custom_url LIKE '%fbcdn%'"
) . "\n";
$opts = json_decode((string) get_option('aioseo_options'), true);
$fb = $opts['social']['facebook'] ?? [];
echo 'defaultSrc=' . ($fb['defaultImageSource'] ?? '') . "\n";
echo 'defaultImg=' . ($fb['defaultImageCustomFields'] ?? '') . "\n";
echo 'postImageSource=' . ($fb['postImageSource'] ?? ($fb['general']['postImageSource'] ?? '')) . "\n";
echo json_encode(array_keys($fb), JSON_UNESCAPED_UNICODE) . "\n";
// sample product row
$pid = 2583;
$row = $wpdb->get_row($wpdb->prepare(
    "SELECT og_image_type, og_image_url, og_image_custom_url, og_image_source FROM {$wpdb->prefix}aioseo_posts WHERE post_id=%d",
    $pid
));
echo "product {$pid}: " . json_encode($row, JSON_UNESCAPED_UNICODE) . "\n";
$page = 1976;
$row = $wpdb->get_row($wpdb->prepare(
    "SELECT og_image_type, LEFT(og_image_url,120) u, og_image_custom_url, title, LEFT(description,80) d FROM {$wpdb->prefix}aioseo_posts WHERE post_id=%d",
    $page
));
echo "shop {$page}: " . json_encode($row, JSON_UNESCAPED_UNICODE) . "\n";
