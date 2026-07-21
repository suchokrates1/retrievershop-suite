<?php
/**
 * Force homepage OG image to local logo (not expired FB CDN).
 * Re-pick featured from in-stock products whose titles lack size tokens.
 */
require '/var/www/html/wp-load.php';
header('Content-Type: text/plain; charset=utf-8');
wp_set_current_user(1);

$LOGO = 'https://retrievershop.pl/wp-content/uploads/2024/08/retriver-2.png';
$HOME_ID = (int) get_option('page_on_front') ?: 595;

update_post_meta($HOME_ID, '_aioseo_og_image_custom_url', $LOGO);
update_post_meta($HOME_ID, '_aioseo_og_image_type', 'custom');
update_post_meta($HOME_ID, '_aioseo_twitter_image_custom_url', $LOGO);
update_post_meta($HOME_ID, '_aioseo_twitter_image_type', 'custom');

global $wpdb;
$table = $wpdb->prefix . 'aioseo_posts';
if ($wpdb->get_var($wpdb->prepare('SHOW TABLES LIKE %s', $table)) === $table) {
    $wpdb->update(
        $table,
        [
            'og_image_type' => 'custom',
            'og_image_custom_url' => $LOGO,
            'og_image_url' => $LOGO,
            'twitter_image_type' => 'custom',
            'twitter_image_custom_url' => $LOGO,
            'twitter_image_url' => $LOGO,
        ],
        ['post_id' => $HOME_ID]
    );
    echo "aioseo_posts og updated\n";
}

// Prefer featured without trailing size in title
$size_re = '/\b(XXS|XS|S|M|L|XL|XXL|2XL|3XL)\b/u';
$color_re = '/\b(czarn|biał|czerwon|niebiesk|zielon|różow|fioletow|pomarańcz|szar|granatow|limonk|turkus|liliow)/iu';
$q = new WP_Query([
    'post_type' => 'product',
    'post_status' => 'publish',
    'posts_per_page' => 40,
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
    $name = get_the_title();
    if (preg_match($size_re, $name) || preg_match($color_re, $name)) {
        continue;
    }
    $p = wc_get_product(get_the_ID());
    if ($p && $p->is_in_stock() && has_post_thumbnail()) {
        $good[] = (int) get_the_ID();
    }
}
wp_reset_postdata();
echo 'good_featured_candidates=' . implode(',', array_slice($good, 0, 8)) . "\n";

foreach (wc_get_featured_product_ids() as $fid) {
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

if (class_exists('\\Elementor\\Plugin')) {
    \Elementor\Plugin::$instance->files_manager->clear_cache();
}
echo "DONE\n";
