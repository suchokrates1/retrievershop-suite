<?php
require '/var/www/html/wp-load.php';
global $wpdb;
$q = new WP_Query(['post_type' => 'product', 's' => 'Cordura', 'posts_per_page' => 8]);
while ($q->have_posts()) {
    $q->the_post();
    $p = wc_get_product(get_the_ID());
    echo get_the_ID() . ' desc=' . strlen(wp_strip_all_tags($p->get_description())) . ' ' . $p->get_name() . "\n";
}
$p = wc_get_product(4193);
echo '4193 desc=' . strlen(wp_strip_all_tags($p->get_description())) . ' name=' . $p->get_name() . "\n";
$empty = $wpdb->get_var(
    "SELECT COUNT(*) FROM {$wpdb->posts} WHERE post_type='product' AND post_status='publish' AND (post_content IS NULL OR TRIM(post_content)='')"
);
echo "empty_desc={$empty}\n";
$typo = $wpdb->get_var(
    "SELECT COUNT(*) FROM {$wpdb->posts} WHERE post_type='product' AND post_status='publish' AND (post_title LIKE '%Trelove%' OR post_title LIKE '%Fronr%')"
);
echo "typo_titles={$typo}\n";
echo 'tagline=' . get_option('blogdescription') . "\n";
