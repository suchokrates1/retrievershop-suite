<?php
/**
 * One-shot SEO audit for retrievershop WP (run via docker exec php).
 */
require '/var/www/html/wp-load.php';

header('Content-Type: text/plain; charset=utf-8');

function line($k, $v = null) {
    if (is_array($v) || is_object($v)) {
        $v = json_encode($v, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    }
    echo $k . (func_num_args() > 1 ? ': ' . $v : '') . PHP_EOL;
}

line('=== SITE ===');
line('blogname', get_option('blogname'));
line('blogdescription', get_option('blogdescription'));
line('siteurl', get_option('siteurl'));
line('home', get_option('home'));
line('permalink', get_option('permalink_structure'));
line('blog_public', get_option('blog_public'));
line('timezone', wp_timezone_string());
line('date_format', get_option('date_format'));
line('admin_email', get_option('admin_email'));
line('users_can_register', get_option('users_can_register'));

line('=== WOO STORE ===');
line('store_address', get_option('woocommerce_store_address'));
line('store_address_2', get_option('woocommerce_store_address_2'));
line('store_city', get_option('woocommerce_store_city'));
line('store_postcode', get_option('woocommerce_store_postcode'));
line('default_country', get_option('woocommerce_default_country'));
line('currency', get_option('woocommerce_currency'));
line('currency_pos', get_option('woocommerce_currency_pos'));
line('weight_unit', get_option('woocommerce_weight_unit'));
line('dimension_unit', get_option('woocommerce_dimension_unit'));
line('calc_taxes', get_option('woocommerce_calc_taxes'));
line('prices_include_tax', get_option('woocommerce_prices_include_tax'));
line('tax_display_shop', get_option('woocommerce_tax_display_shop'));
line('enable_reviews', get_option('woocommerce_enable_reviews'));
line('review_rating_required', get_option('woocommerce_review_rating_required'));
line('placeholder_image', get_option('woocommerce_placeholder_image'));
line('shop_page_id', get_option('woocommerce_shop_page_id'));
line('cart_page_id', get_option('woocommerce_cart_page_id'));
line('checkout_page_id', get_option('woocommerce_checkout_page_id'));
line('myaccount_page_id', get_option('woocommerce_myaccount_page_id'));
line('terms_page_id', get_option('woocommerce_terms_page_id'));

line('=== PLUGINS ACTIVE ===');
if (!function_exists('get_plugins')) {
    require_once ABSPATH . 'wp-admin/includes/plugin.php';
}
foreach (get_option('active_plugins', []) as $p) {
    line('-', $p);
}

line('=== THEME ===');
$theme = wp_get_theme();
line('theme', $theme->get('Name') . ' ' . $theme->get('Version'));
line('parent', $theme->parent() ? $theme->parent()->get('Name') : '');

line('=== AIOSEO / SEO OPTIONS (keys) ===');
global $wpdb;
$seo_opts = $wpdb->get_results(
    "SELECT option_name, LENGTH(option_value) AS len FROM {$wpdb->options}
     WHERE option_name LIKE '%aioseo%' OR option_name LIKE '%yoast%' OR option_name LIKE '%rank_math%'
     ORDER BY option_name LIMIT 40"
);
foreach ($seo_opts as $row) {
    line($row->option_name, 'len=' . $row->len);
}

// AIOSEO local SEO / social if present
if (class_exists('\\AIOSEO\\Plugin\\AIOSEO') || defined('AIOSEO_VERSION')) {
    line('AIOSEO_VERSION', defined('AIOSEO_VERSION') ? AIOSEO_VERSION : 'class');
}
$aioseo = get_option('aioseo_options');
if (is_string($aioseo)) {
    $decoded = json_decode($aioseo, true);
    if (is_array($decoded)) {
        $search = $decoded['searchAppearance']['global'] ?? null;
        $social = $decoded['social']['profiles'] ?? null;
        $local = $decoded['localBusiness'] ?? ($decoded['localSeo'] ?? null);
        line('aioseo.searchAppearance.global', $search);
        line('aioseo.social.profiles', $social);
        line('aioseo.local', is_array($local) ? array_intersect_key($local, array_flip(['locations','business','openingHours','maps'])) : $local);
    }
}

line('=== PRODUCT STATS ===');
$counts = wp_count_posts('product');
line('products', $counts);
$published = (int) ($counts->publish ?? 0);

// Sample products: featured / on homepage issues
$q = new WP_Query([
    'post_type' => 'product',
    'post_status' => 'publish',
    'posts_per_page' => 8,
    'orderby' => 'modified',
    'order' => 'DESC',
]);
line('=== RECENT PRODUCTS ===');
while ($q->have_posts()) {
    $q->the_post();
    $id = get_the_ID();
    $product = wc_get_product($id);
    $thumb = get_post_thumbnail_id($id);
    $desc = $product ? $product->get_description() : '';
    $short = $product ? $product->get_short_description() : '';
    $sku = $product ? $product->get_sku() : '';
    line(sprintf(
        '#%d | stock=%s | thumb=%s | sku=%s | title=%s | desc_len=%d short_len=%d | slug=%s',
        $id,
        $product ? ($product->is_in_stock() ? 'in' : 'out') : '?',
        $thumb ? $thumb : 'NONE',
        $sku ?: '-',
        get_the_title(),
        strlen(wp_strip_all_tags($desc)),
        strlen(wp_strip_all_tags($short)),
        get_post_field('post_name', $id)
    ));
}
wp_reset_postdata();

line('=== PRODUCTS WITHOUT THUMBNAIL ===');
$no_thumb = new WP_Query([
    'post_type' => 'product',
    'post_status' => 'publish',
    'posts_per_page' => 20,
    'meta_query' => [
        [
            'key' => '_thumbnail_id',
            'compare' => 'NOT EXISTS',
        ],
    ],
]);
line('count_no_thumb_sample', $no_thumb->found_posts);
while ($no_thumb->have_posts()) {
    $no_thumb->the_post();
    line('-', get_the_ID() . ' ' . get_the_title());
}
wp_reset_postdata();

line('=== PRODUCTS EMPTY DESCRIPTION ===');
$empty_desc = $wpdb->get_var(
    "SELECT COUNT(*) FROM {$wpdb->posts} p
     WHERE p.post_type='product' AND p.post_status='publish'
     AND (p.post_content IS NULL OR TRIM(p.post_content)='')"
);
line('empty_description_count', $empty_desc);

line('=== DUPLICATE TITLES ===');
$dups = $wpdb->get_results(
    "SELECT post_title, COUNT(*) c FROM {$wpdb->posts}
     WHERE post_type='product' AND post_status='publish'
     GROUP BY post_title HAVING c>1 ORDER BY c DESC LIMIT 15"
);
foreach ($dups as $d) {
    line($d->c . 'x', $d->post_title);
}

line('=== TYPO / BAD SLUGS SAMPLE ===');
$bad = $wpdb->get_results(
    "SELECT ID, post_title, post_name FROM {$wpdb->posts}
     WHERE post_type='product' AND post_status='publish'
     AND (post_title LIKE '%Trelove%' OR post_title LIKE '%Fronr%' OR post_name LIKE '%trelove%'
          OR post_name LIKE '%fronr%' OR post_name LIKE '%czerwonw%' OR post_title LIKE '%czerwonw%')
     LIMIT 20"
);
foreach ($bad as $b) {
    line("#{$b->ID}", $b->post_title . ' | ' . $b->post_name);
}

line('=== PAGES (legal / about) ===');
$pages = get_pages(['sort_column' => 'post_title']);
foreach ($pages as $p) {
    line("#{$p->ID}", $p->post_title . ' | /' . $p->post_name . '/');
}

line('=== CATEGORIES ===');
$terms = get_terms(['taxonomy' => 'product_cat', 'hide_empty' => false]);
if (!is_wp_error($terms)) {
    foreach ($terms as $t) {
        $desc_len = strlen(trim(wp_strip_all_tags($t->description)));
        line($t->slug, "{$t->name} count={$t->count} desc_len={$desc_len}");
    }
}

line('DONE');
