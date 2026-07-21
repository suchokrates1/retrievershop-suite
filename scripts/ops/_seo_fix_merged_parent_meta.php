<?php
require '/var/www/html/wp-load.php';
header('Content-Type: text/plain; charset=utf-8');
$pid = (int) ($argv[1] ?? 3586);
$title = 'Szelki dla psa Truelove Front Line Premium | Retriever Shop';
$desc = 'Szelki Front Line Premium Truelove — wybierz kolor i rozmiar. Regulacja w czterech punktach, odblaski, szybka wysyłka z Legnicy.';
update_post_meta($pid, '_aioseo_title', $title);
update_post_meta($pid, '_aioseo_description', $desc);
global $wpdb;
$table = $wpdb->prefix . 'aioseo_posts';
$wpdb->update($table, [
    'title' => $title,
    'description' => $desc,
    'og_title' => 'Szelki dla psa Truelove Front Line Premium',
    'og_description' => $desc,
], ['post_id' => $pid]);
// ensure post title clean
wp_update_post(['ID' => $pid, 'post_title' => 'Szelki dla psa Truelove Front Line Premium']);
echo "seo fixed #{$pid}\n";
$p = wc_get_product($pid);
if ($p) {
    echo 'type=' . $p->get_type() . "\n";
    echo 'attrs=' . count($p->get_attributes()) . "\n";
    echo 'children=' . count($p->get_children()) . "\n";
    foreach ($p->get_attributes() as $a) {
        echo ' - ' . $a->get_name() . ' var=' . ($a->get_variation() ? '1' : '0') . ' opts=' . implode(',', $a->get_options()) . "\n";
    }
}
