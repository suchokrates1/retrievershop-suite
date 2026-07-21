<?php
require '/var/www/html/wp-load.php';
header('Content-Type: text/plain; charset=utf-8');
global $wpdb;

$title = 'Szelki dla psa Truelove Front Line Premium';
$rows = $wpdb->get_results($wpdb->prepare(
    "SELECT ID, post_name, post_status FROM {$wpdb->posts}
     WHERE post_type='product' AND post_status='publish' AND post_title=%s
     ORDER BY ID",
    $title
));
echo "title={$title} count=" . count($rows) . "\n";
foreach ($rows as $r) {
    $p = wc_get_product((int) $r->ID);
    $type = $p ? $p->get_type() : '?';
    $thumb = get_post_thumbnail_id((int) $r->ID);
    $colors = wp_get_post_terms((int) $r->ID, 'pa_kolor', ['fields' => 'names']);
    $color = is_wp_error($colors) ? [] : $colors;
    echo "#{$r->ID} type={$type} thumb={$thumb} colors=" . implode(',', $color) . " slug={$r->post_name}\n";
}

// slug dups: product vs variation
$slug = 'pas-samochodowy-dla-psa-truelove-premium';
$srows = $wpdb->get_results($wpdb->prepare(
    "SELECT ID, post_type, post_status, post_title FROM {$wpdb->posts} WHERE post_name=%s",
    $slug
));
echo "\nslug={$slug}\n";
foreach ($srows as $r) {
    echo "#{$r->ID} {$r->post_type}/{$r->post_status} {$r->post_title}\n";
}

// shop / o-nas aioseo
foreach ([1976, 1037, 14, 2393] as $pid) {
    $row = $wpdb->get_row($wpdb->prepare(
        "SELECT title, description FROM {$wpdb->prefix}aioseo_posts WHERE post_id=%d",
        $pid
    ));
    echo "\npage #{$pid} " . get_the_title($pid) . "\n";
    echo "  title=" . ($row->title ?? '') . "\n";
    echo "  desc=" . substr((string) ($row->description ?? ''), 0, 180) . "\n";
}

// homepage h1 via content length
$home = get_post(595);
echo "\nhome content_len=" . strlen($home->post_content ?? '') . "\n";
