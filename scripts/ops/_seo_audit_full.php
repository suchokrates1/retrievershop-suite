<?php
/**
 * Duży audyt SEO retrievershop.pl — WP/Woo/AIOSEO + higiena katalogu.
 * Run: docker exec retrievershop-wp php /tmp/_seo_audit_full.php
 */
require '/var/www/html/wp-load.php';

header('Content-Type: text/plain; charset=utf-8');
global $wpdb;

function line($k, $v = null) {
    if (func_num_args() > 1) {
        if (is_array($v) || is_object($v)) {
            $v = json_encode($v, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
        }
        echo $k . ': ' . $v . PHP_EOL;
    } else {
        echo $k . PHP_EOL;
    }
}

function pct($n, $d) {
    if (!$d) {
        return '0%';
    }
    return round(100 * $n / $d, 1) . '%';
}

$PHONE_CANON = '782865895';
$issues = [];
$warns = [];

line('=== AUDYT SEO FULL ' . gmdate('Y-m-d H:i:s') . ' UTC ===');

line('=== SITE ===');
line('blogname', get_option('blogname'));
line('blogdescription', get_option('blogdescription'));
line('siteurl', get_option('siteurl'));
line('home', get_option('home'));
line('permalink', get_option('permalink_structure'));
line('blog_public', get_option('blog_public'));
line('timezone', wp_timezone_string());
line('admin_email', get_option('admin_email'));
if ((string) get_option('blog_public') !== '1') {
    $issues[] = 'blog_public != 1 (noindex sitewide?)';
}
$tagline = (string) get_option('blogdescription');
if ($tagline === '' || stripos($tagline, 'wordpress') !== false) {
    $issues[] = 'słaby/pusty tagline';
}

line('=== WOO STORE ===');
line('address', trim(get_option('woocommerce_store_address') . ' ' . get_option('woocommerce_store_address_2')));
line('city', get_option('woocommerce_store_city'));
line('postcode', get_option('woocommerce_store_postcode'));
line('country', get_option('woocommerce_default_country'));
line('currency', get_option('woocommerce_currency'));
line('calc_taxes', get_option('woocommerce_calc_taxes'));
line('prices_include_tax', get_option('woocommerce_prices_include_tax'));
line('shop_page_id', get_option('woocommerce_shop_page_id'));
line('placeholder_image', get_option('woocommerce_placeholder_image'));

line('=== PLUGINS / THEME ===');
if (!function_exists('get_plugins')) {
    require_once ABSPATH . 'wp-admin/includes/plugin.php';
}
$active = get_option('active_plugins', []);
foreach ($active as $p) {
    line('-', $p);
}
$mu = get_mu_plugins();
foreach (array_keys($mu) as $m) {
    line('mu', $m);
}
$theme = wp_get_theme();
line('theme', $theme->get('Name') . ' ' . $theme->get('Version'));
line('parent', $theme->parent() ? $theme->parent()->get('Name') . ' ' . $theme->parent()->get('Version') : '');

line('=== AIOSEO / SEARCH APPEARANCE ===');
line('AIOSEO_VERSION', defined('AIOSEO_VERSION') ? AIOSEO_VERSION : 'n/a');
$aioseo_raw = get_option('aioseo_options');
$aioseo = is_string($aioseo_raw) ? json_decode($aioseo_raw, true) : (is_array($aioseo_raw) ? $aioseo_raw : null);
if (!is_array($aioseo)) {
    $issues[] = 'brak aioseo_options';
} else {
    $global = $aioseo['searchAppearance']['global'] ?? [];
    $org = $aioseo['searchAppearance']['global']['schema'] ?? ($aioseo['schema'] ?? []);
    $social = $aioseo['social'] ?? [];
    $fb = $social['facebook'] ?? [];
    $profiles = $social['profiles'] ?? [];
    line('siteTitle', $global['siteTitle'] ?? '');
    line('metaDescription', $global['metaDescription'] ?? '');
    line('separator', $global['separator'] ?? '');
    line('robots', $global['robotsMeta'] ?? ($global['robots'] ?? ''));
    line('fb.defaultImage', $fb['defaultImageCustomFields'] ?? ($fb['defaultImage'] ?? ''));
    line('fb.homeImage', $fb['homePageImageCustomFields'] ?? '');
    line('social.profiles', $profiles);

    $blob = json_encode($aioseo, JSON_UNESCAPED_UNICODE);
    if (preg_match('/605\s*864\s*663|\+48605864663|605864663/', $blob)) {
        $issues[] = 'AIOSEO nadal zawiera stary telefon 605 864 663';
    }
    if (strpos($blob, $PHONE_CANON) === false && strpos($blob, '782 865 895') === false) {
        $warns[] = 'AIOSEO blob bez kanonicznego telefonu 782 865 895';
    }
    $og = (string) ($fb['defaultImageCustomFields'] ?? '');
    if ($og === '' || stripos($og, 'facebook.com') !== false || stripos($og, 'fbcdn') !== false) {
        $issues[] = 'OG default image puste lub Facebook CDN';
    }
}

// Per-page AIOSEO meta (home + kontakt)
line('=== KEY PAGES META ===');
$home_id = (int) get_option('page_on_front');
$shop_id = (int) get_option('woocommerce_shop_page_id');
$kontakt = get_page_by_path('kontakt');
$page_ids = array_filter([
    'home' => $home_id,
    'shop' => $shop_id,
    'kontakt' => $kontakt ? (int) $kontakt->ID : 0,
]);
foreach ($page_ids as $label => $pid) {
    if (!$pid) {
        line($label, 'MISSING');
        $issues[] = "brak strony $label";
        continue;
    }
    $title = get_the_title($pid);
    $slug = get_post_field('post_name', $pid);
    $ai_title = get_post_meta($pid, '_aioseo_title', true);
    $ai_desc = get_post_meta($pid, '_aioseo_description', true);
    // AIOSEO 4 stores in aioseo_posts table sometimes
    $row = $wpdb->get_row($wpdb->prepare(
        "SELECT title, description, canonical_url, robots_noindex FROM {$wpdb->prefix}aioseo_posts WHERE post_id=%d",
        $pid
    ));
    line($label, "#{$pid} {$title} /{$slug}/");
    line("  meta_title", $ai_title ?: ($row->title ?? ''));
    line("  meta_desc", $ai_desc ?: ($row->description ?? ''));
    line("  noindex", $row->robots_noindex ?? '');
    $desc_check = (string) ($ai_desc ?: ($row->description ?? ''));
    if ($label === 'kontakt' && (stripos($desc_check, 'elementor') !== false || strlen(wp_strip_all_tags($desc_check)) > 320)) {
        $issues[] = 'Kontakt meta description wygląda na śmieci/Elementor';
    }
    if ($label === 'home' && strlen(trim(wp_strip_all_tags($desc_check))) < 50) {
        $warns[] = 'Home meta description krótka/pusta';
    }
}

line('=== PRODUCT COUNTS ===');
$counts = wp_count_posts('product');
$published = (int) ($counts->publish ?? 0);
$draft = (int) ($counts->draft ?? 0);
$private = (int) ($counts->private ?? 0);
line('publish', $published);
line('draft', $draft);
line('private', $private);
line('trash', (int) ($counts->trash ?? 0));

$empty_desc = (int) $wpdb->get_var(
    "SELECT COUNT(*) FROM {$wpdb->posts} p
     WHERE p.post_type='product' AND p.post_status='publish'
     AND (p.post_content IS NULL OR TRIM(p.post_content)='')"
);
$short_desc = (int) $wpdb->get_var(
    "SELECT COUNT(*) FROM {$wpdb->posts} p
     WHERE p.post_type='product' AND p.post_status='publish'
     AND LENGTH(TRIM(REGEXP_REPLACE(p.post_content, '<[^>]+>', ''))) BETWEEN 1 AND 80"
);
$empty_excerpt = (int) $wpdb->get_var(
    "SELECT COUNT(*) FROM {$wpdb->posts} p
     WHERE p.post_type='product' AND p.post_status='publish'
     AND (p.post_excerpt IS NULL OR TRIM(p.post_excerpt)='')"
);
$no_thumb = (int) $wpdb->get_var(
    "SELECT COUNT(*) FROM {$wpdb->posts} p
     LEFT JOIN {$wpdb->postmeta} m ON m.post_id=p.ID AND m.meta_key='_thumbnail_id'
     WHERE p.post_type='product' AND p.post_status='publish'
     AND (m.meta_value IS NULL OR m.meta_value='' OR m.meta_value='0')"
);
$outofstock = (int) $wpdb->get_var(
    "SELECT COUNT(*) FROM {$wpdb->posts} p
     INNER JOIN {$wpdb->postmeta} m ON m.post_id=p.ID AND m.meta_key='_stock_status' AND m.meta_value='outofstock'
     WHERE p.post_type='product' AND p.post_status='publish'"
);
$no_sku = (int) $wpdb->get_var(
    "SELECT COUNT(*) FROM {$wpdb->posts} p
     LEFT JOIN {$wpdb->postmeta} m ON m.post_id=p.ID AND m.meta_key='_sku'
     WHERE p.post_type='product' AND p.post_status='publish'
     AND (m.meta_value IS NULL OR m.meta_value='')"
);

line('empty_description', "{$empty_desc} (" . pct($empty_desc, $published) . ')');
line('very_short_description_1_80', "{$short_desc} (" . pct($short_desc, $published) . ')');
line('empty_short_description', "{$empty_excerpt} (" . pct($empty_excerpt, $published) . ')');
line('no_thumbnail', "{$no_thumb} (" . pct($no_thumb, $published) . ')');
line('outofstock', "{$outofstock} (" . pct($outofstock, $published) . ')');
line('no_sku', "{$no_sku} (" . pct($no_sku, $published) . ')');

if ($empty_desc > 0) {
    $issues[] = "produkty bez opisu: {$empty_desc}";
}
if ($no_thumb > 0) {
    $issues[] = "produkty bez miniatury: {$no_thumb}";
}

line('=== TITLE / SLUG HYGIENE ===');
$typo = $wpdb->get_results(
    "SELECT ID, post_title, post_name FROM {$wpdb->posts}
     WHERE post_type='product' AND post_status='publish'
     AND (
       post_title LIKE '%Trelove%' OR post_title LIKE '%Truelve%' OR post_title LIKE '%Fronr%'
       OR post_title LIKE '%ptemium%' OR post_title LIKE '%Premiumm%' OR post_title LIKE '%średnieho%'
       OR post_title LIKE '%czerwonw%' OR post_name LIKE '%trelove%' OR post_name LIKE '%fronr%'
       OR post_name LIKE '%czerwonw%' OR post_name LIKE '%truelve%' OR post_name LIKE '%ptemium%'
     )
     ORDER BY ID LIMIT 40"
);
line('typo_count', count($typo));
foreach ($typo as $b) {
    line("typo #{$b->ID}", $b->post_title . ' | ' . $b->post_name);
}
if ($typo) {
    $issues[] = 'literówki w tytułach/slugach: ' . count($typo);
}

$size_in_title = (int) $wpdb->get_var(
    "SELECT COUNT(*) FROM {$wpdb->posts}
     WHERE post_type='product' AND post_status='publish'
     AND (
       post_title REGEXP '[[:space:]](XXS|XS|S|M|L|XL|XXL|3XL)([[:space:]]|$)'
       OR post_title REGEXP '[[:space:]](xxs|xs|s|m|l|xl|xxl|3xl)([[:space:]]|$)'
     )"
);
line('titles_with_size_token', $size_in_title);
if ($size_in_title > 10) {
    $warns[] = "tytuły z tokenem rozmiaru: {$size_in_title}";
}

$dups = $wpdb->get_results(
    "SELECT post_title, COUNT(*) c FROM {$wpdb->posts}
     WHERE post_type='product' AND post_status='publish'
     GROUP BY post_title HAVING c>1 ORDER BY c DESC LIMIT 20"
);
line('duplicate_titles_groups', count($dups));
foreach ($dups as $d) {
    line("dup {$d->c}x", $d->post_title);
}

$dup_slugs = $wpdb->get_results(
    "SELECT post_name, COUNT(*) c FROM {$wpdb->posts}
     WHERE post_type IN ('product','product_variation') AND post_status IN ('publish','private')
     GROUP BY post_name HAVING c>1 ORDER BY c DESC LIMIT 15"
);
line('duplicate_slugs_groups', count($dup_slugs));
foreach ($dup_slugs as $d) {
    line("slugdup {$d->c}x", $d->post_name);
}

line('=== IMAGE ALT ===');
$imgs = (int) $wpdb->get_var(
    "SELECT COUNT(*) FROM {$wpdb->posts} WHERE post_type='attachment' AND post_mime_type LIKE 'image/%'"
);
$empty_alt = (int) $wpdb->get_var(
    "SELECT COUNT(*) FROM {$wpdb->posts} p
     INNER JOIN {$wpdb->postmeta} m ON m.post_id=p.ID AND m.meta_key='_wp_attachment_image_alt'
     WHERE p.post_type='attachment' AND p.post_mime_type LIKE 'image/%'
     AND TRIM(m.meta_value)=''"
);
$missing_alt_meta = (int) $wpdb->get_var(
    "SELECT COUNT(*) FROM {$wpdb->posts} p
     LEFT JOIN {$wpdb->postmeta} m ON m.post_id=p.ID AND m.meta_key='_wp_attachment_image_alt'
     WHERE p.post_type='attachment' AND p.post_mime_type LIKE 'image/%'
     AND m.meta_id IS NULL"
);
line('images_total', $imgs);
line('images_empty_alt', $empty_alt);
line('images_missing_alt_meta', $missing_alt_meta);
if (($empty_alt + $missing_alt_meta) > 50) {
    $warns[] = 'dużo obrazków bez ALT: ' . ($empty_alt + $missing_alt_meta);
}

line('=== CATEGORIES ===');
$terms = get_terms(['taxonomy' => 'product_cat', 'hide_empty' => false]);
$cat_empty_desc = 0;
if (!is_wp_error($terms)) {
    foreach ($terms as $t) {
        $desc_len = strlen(trim(wp_strip_all_tags($t->description)));
        if ($desc_len < 40 && $t->slug !== 'uncategorized') {
            $cat_empty_desc++;
        }
        line($t->slug, "{$t->name} count={$t->count} desc_len={$desc_len}");
    }
}
line('categories_weak_desc', $cat_empty_desc);
if ($cat_empty_desc > 0) {
    $warns[] = "kategorie ze słabym opisem: {$cat_empty_desc}";
}

line('=== ATTRIBUTES / TAXONOMIES ===');
foreach (['pa_kolor', 'pa_rozmiar', 'pa_marka', 'product_tag', 'product_brand'] as $tax) {
    if (!taxonomy_exists($tax)) {
        line($tax, 'MISSING');
        continue;
    }
    $c = (int) $wpdb->get_var($wpdb->prepare(
        "SELECT COUNT(*) FROM {$wpdb->term_taxonomy} WHERE taxonomy=%s",
        $tax
    ));
    line($tax, $c);
}

line('=== REDIRECTS MU ===');
$redir_file = WP_CONTENT_DIR . '/mu-plugins/retriever-seo-slug-redirects.php';
line('slug_redirects_mu', file_exists($redir_file) ? 'present' : 'MISSING');
if (!file_exists($redir_file)) {
    $warns[] = 'brak MU slug redirects';
}
$nl_file = WP_CONTENT_DIR . '/mu-plugins/retriever-newsletter.php';
line('newsletter_mu', file_exists($nl_file) ? 'present' : 'MISSING');

line('=== ROBOTS / SITEMAP HINTS ===');
$blog_public = get_option('blog_public');
line('blog_public', $blog_public);
// AIOSEO sitemap usually at /sitemap.xml
line('aioseo_sitemap_enable', $aioseo['sitemap']['general']['enable'] ?? ($aioseo['sitemap'] ?? 'unknown'));

line('=== SAMPLE RECENT PRODUCTS ===');
$q = new WP_Query([
    'post_type' => 'product',
    'post_status' => 'publish',
    'posts_per_page' => 12,
    'orderby' => 'modified',
    'order' => 'DESC',
]);
while ($q->have_posts()) {
    $q->the_post();
    $id = get_the_ID();
    $product = wc_get_product($id);
    $thumb = get_post_thumbnail_id($id);
    $desc = $product ? wp_strip_all_tags($product->get_description()) : '';
    $short = $product ? wp_strip_all_tags($product->get_short_description()) : '';
    line(sprintf(
        '#%d | %s | thumb=%s | sku=%s | desc=%d short=%d | %s',
        $id,
        $product && $product->is_in_stock() ? 'IN' : 'OUT',
        $thumb ?: 'NONE',
        $product ? ($product->get_sku() ?: '-') : '-',
        strlen($desc),
        strlen($short),
        get_the_title()
    ));
}
wp_reset_postdata();

line('=== EMPTY DESC SAMPLE ===');
$empty_q = $wpdb->get_results(
    "SELECT ID, post_title FROM {$wpdb->posts}
     WHERE post_type='product' AND post_status='publish'
     AND (post_content IS NULL OR TRIM(post_content)='')
     ORDER BY ID DESC LIMIT 15"
);
foreach ($empty_q as $r) {
    line("empty #{$r->ID}", $r->post_title);
}

line('=== NO THUMB SAMPLE ===');
$nth = $wpdb->get_results(
    "SELECT p.ID, p.post_title FROM {$wpdb->posts} p
     LEFT JOIN {$wpdb->postmeta} m ON m.post_id=p.ID AND m.meta_key='_thumbnail_id'
     WHERE p.post_type='product' AND p.post_status='publish'
     AND (m.meta_value IS NULL OR m.meta_value='' OR m.meta_value='0')
     ORDER BY p.ID DESC LIMIT 15"
);
foreach ($nth as $r) {
    line("nothumb #{$r->ID}", $r->post_title);
}

line('=== PAGES INDEX ===');
$pages = get_pages(['sort_column' => 'post_title', 'post_status' => 'publish']);
foreach ($pages as $p) {
    $row = $wpdb->get_row($wpdb->prepare(
        "SELECT robots_noindex FROM {$wpdb->prefix}aioseo_posts WHERE post_id=%d",
        $p->ID
    ));
    line("#{$p->ID}", $p->post_title . ' | /' . $p->post_name . '/ noindex=' . ($row->robots_noindex ?? '?'));
}

line('=== SCORECARD ===');
foreach ($issues as $i) {
    line('ISSUE', $i);
}
foreach ($warns as $w) {
    line('WARN', $w);
}
line('issues_count', count($issues));
line('warns_count', count($warns));
line('DONE');
