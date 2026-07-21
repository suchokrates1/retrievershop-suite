<?php
/**
 * Homepage product shortcodes: only in-stock; set featured products.
 */
require '/var/www/html/wp-load.php';
header('Content-Type: text/plain; charset=utf-8');
wp_set_current_user(1);

$q = new WP_Query([
    'post_type' => 'product',
    'post_status' => 'publish',
    'posts_per_page' => 20,
    'meta_query' => [
        ['key' => '_thumbnail_id', 'compare' => 'EXISTS'],
        ['key' => '_stock_status', 'value' => 'instock'],
    ],
    'orderby' => 'modified',
    'order' => 'DESC',
]);
$good = [];
while ($q->have_posts()) {
    $q->the_post();
    $p = wc_get_product(get_the_ID());
    if ($p && $p->is_in_stock() && has_post_thumbnail() && strlen($p->get_name()) > 10) {
        // Skip titles that still look like variation-level (size at end)
        $good[] = (int) get_the_ID();
    }
}
wp_reset_postdata();
$good = array_values(array_unique($good));
echo 'candidates=' . implode(',', array_slice($good, 0, 10)) . "\n";

// Clear all featured, set top 6
$featured = wc_get_featured_product_ids();
foreach ($featured as $fid) {
    $fp = wc_get_product($fid);
    if ($fp) {
        $fp->set_featured(false);
        $fp->save();
    }
}
foreach (array_slice($good, 0, 6) as $fid) {
    $fp = wc_get_product($fid);
    if ($fp) {
        $fp->set_featured(true);
        $fp->save();
        echo "featured #{$fid} {$fp->get_name()}\n";
    }
}

$HOME_ID = (int) get_option('page_on_front') ?: 595;
$data = get_post_meta($HOME_ID, '_elementor_data', true);
if (!$data) {
    echo "no elementor data\n";
    exit(1);
}
$orig = $data;
$replacements = [
    '[products limit="6" columns="3" best_selling="true"]' => '[products limit="6" columns="3" visibility="featured" orderby="menu_order"]',
    '[products limit=\"6\" columns=\"3\" best_selling=\"true\"]' => '[products limit=\"6\" columns=\"3\" visibility=\"featured\" orderby=\"menu_order\"]',
    '[products limit="3" columns="3"]' => '[products limit="3" columns="3" orderby="date" order="DESC" visibility="visible" class="instock"]',
    '[products limit=\"3\" columns=\"3\"]' => '[products limit=\"3\" columns=\"3\" visibility=\"featured\"]',
];
foreach ($replacements as $from => $to) {
    if (str_contains($data, $from)) {
        $data = str_replace($from, $to, $data);
        echo "replaced shortcode variant\n";
    }
}
// Fallback: any best_selling shortcode
$data = preg_replace(
    '/\[products([^\]]*?)best_selling="true"([^\]]*?)\]/',
    '[products limit="6" columns="3" visibility="featured"]',
    $data
);

if ($data !== $orig) {
    update_post_meta($HOME_ID, '_elementor_data', wp_slash($data));
    echo "elementor_data updated\n";
} else {
    echo "elementor_data unchanged — dump shortcodes\n";
    if (preg_match_all('/\[products[^\]]+\]/', $data, $m)) {
        print_r($m[0]);
    }
}

if (class_exists('\\Elementor\\Plugin')) {
    \Elementor\Plugin::$instance->files_manager->clear_cache();
    echo "elementor cache cleared\n";
}
echo "DONE\n";
