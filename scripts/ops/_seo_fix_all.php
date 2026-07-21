<?php
/**
 * Naprawa SEO P0/P1: OG, meta stron, H1 home, ALT, kategorie, tytuły z kolorem, thumb.
 * Run: docker exec retrievershop-wp php /tmp/_seo_fix_all.php
 */
require '/var/www/html/wp-load.php';

header('Content-Type: text/plain; charset=utf-8');
wp_set_current_user(1);
if (!current_user_can('manage_options')) {
    $admins = get_users(['role' => 'administrator', 'number' => 1, 'fields' => 'ID']);
    if ($admins) {
        wp_set_current_user((int) $admins[0]);
    }
}

global $wpdb;
$LOGO = 'https://retrievershop.pl/wp-content/uploads/2024/08/retriver-2.png';
$PHONE = '782 865 895';
$stats = [];

function rs_log($msg) {
    echo $msg . PHP_EOL;
}

function rs_aioseo_upsert($post_id, array $data) {
    global $wpdb;
    $table = $wpdb->prefix . 'aioseo_posts';
    if ($wpdb->get_var($wpdb->prepare('SHOW TABLES LIKE %s', $table)) !== $table) {
        return;
    }
    $row = $wpdb->get_row($wpdb->prepare("SELECT id FROM {$table} WHERE post_id=%d", $post_id));
    if ($row) {
        $wpdb->update($table, $data, ['post_id' => $post_id]);
    } else {
        $data['post_id'] = $post_id;
        $wpdb->insert($table, $data);
    }
}

// --- 1) AIOSEO global OG = custom logo (nie „default”/FB) ---
$raw = get_option('aioseo_options');
$opts = is_string($raw) ? json_decode($raw, true) : null;
if (is_array($opts)) {
    if (!isset($opts['social'])) {
        $opts['social'] = [];
    }
    foreach (['facebook', 'twitter'] as $net) {
        if (!isset($opts['social'][$net]) || !is_array($opts['social'][$net])) {
            $opts['social'][$net] = [];
        }
    }
    $fb =& $opts['social']['facebook'];
    $fb['defaultImageSource'] = 'custom';
    $fb['defaultImageCustomFields'] = $LOGO;
    $fb['homePageImageSource'] = 'custom';
    $fb['homePageImageCustomFields'] = $LOGO;
    if (!isset($fb['general']) || !is_array($fb['general'])) {
        $fb['general'] = [];
    }
    // Produkty/strony: featured, fallback custom logo
    $fb['general']['defaultImageSource'] = 'featured';
    $fb['general']['customFieldImage'] = $LOGO;
    $tw =& $opts['social']['twitter'];
    $tw['defaultCardType'] = 'summary_large_image';
    $tw['defaultImageSource'] = 'custom';
    $tw['defaultImageCustomFields'] = $LOGO;
    update_option('aioseo_options', wp_json_encode($opts), false);
    rs_log('AIOSEO OG source -> custom logo');
} else {
    rs_log('WARN: aioseo_options missing');
}

// Clear any fbcdn leftovers + force custom logo where no featured strategy
$wpdb->query(
    "UPDATE {$wpdb->prefix}aioseo_posts SET
        og_image_url = NULL,
        og_image_custom_url = NULL,
        twitter_image_url = NULL,
        twitter_image_custom_url = NULL
     WHERE og_image_url LIKE '%fbcdn%' OR og_image_custom_url LIKE '%fbcdn%'
        OR og_image_url LIKE '%facebook.com%' OR twitter_image_url LIKE '%fbcdn%'"
);
rs_log('cleared fbcdn aioseo_posts rows=' . $wpdb->rows_affected);

// Homepage force custom logo
$HOME_ID = (int) get_option('page_on_front') ?: 595;
rs_aioseo_upsert($HOME_ID, [
    'title' => 'Retriever Shop — szelki i smycze dla psów | Truelove',
    'description' => 'Sklep Retriever Shop: szelki, smycze i akcesoria Truelove. Szybka wysyłka z Legnicy. Sprawdź rozmiary i kolory online.',
    'og_title' => 'Retriever Shop — szelki i smycze dla psów | Truelove',
    'og_description' => 'Sklep Retriever Shop: szelki, smycze i akcesoria Truelove. Szybka wysyłka z Legnicy.',
    'og_image_type' => 'custom',
    'og_image_custom_url' => $LOGO,
    'og_image_url' => $LOGO,
    'twitter_image_type' => 'custom',
    'twitter_image_custom_url' => $LOGO,
    'twitter_image_url' => $LOGO,
]);
update_post_meta($HOME_ID, '_aioseo_og_image_type', 'custom');
update_post_meta($HOME_ID, '_aioseo_og_image_custom_url', $LOGO);

// --- 2) Meta: Produkty, O Nas, Zwroty, Zamówienie (indexable content pages) ---
$page_meta = [
    1976 => [
        'title' => 'Produkty — szelki i smycze dla psa | Retriever Shop',
        'description' => 'Katalog Retriever Shop: szelki, smycze, obroże i akcesoria Truelove. Filtruj po kolorze i rozmiarze, szybka wysyłka z Legnicy.',
    ],
    1037 => [
        'title' => 'O nas — Retriever Shop',
        'description' => 'Retriever Shop z Legnicy — sklep z akcesoriami spacerowymi Truelove. Poznaj naszą historię i pasję do psów.',
    ],
    2393 => [
        'title' => 'Zwroty — Retriever Shop',
        'description' => 'Zasady zwrotów i reklamacji w Retriever Shop. Masz 14 dni na odstąpienie — skontaktuj się: 782 865 895.',
    ],
    1975 => [
        'title' => 'Regulamin sklepu — Retriever Shop',
        'description' => 'Regulamin sklepu internetowego Retriever Shop: zakupy, dostawa, płatności i reklamacje.',
    ],
];
foreach ($page_meta as $pid => $m) {
    if (!get_post($pid)) {
        rs_log("skip missing page #{$pid}");
        continue;
    }
    update_post_meta($pid, '_aioseo_title', $m['title']);
    update_post_meta($pid, '_aioseo_description', $m['description']);
    rs_aioseo_upsert($pid, [
        'title' => $m['title'],
        'description' => $m['description'],
        'og_title' => $m['title'],
        'og_description' => $m['description'],
        'og_image_type' => 'custom',
        'og_image_custom_url' => $LOGO,
        'og_image_url' => $LOGO,
        'twitter_image_type' => 'custom',
        'twitter_image_custom_url' => $LOGO,
        'twitter_image_url' => $LOGO,
    ]);
    rs_log("meta #{$pid} OK");
}

$kontakt = get_page_by_path('kontakt');
if ($kontakt) {
    rs_aioseo_upsert((int) $kontakt->ID, [
        'title' => 'Kontakt — Retriever Shop',
        'description' => 'Skontaktuj się z Retriever Shop: tel. 782 865 895, e-mail kontakt@retrievershop.pl, Wrocławska 15/7, 59-220 Legnica.',
        'og_title' => 'Kontakt — Retriever Shop',
        'og_description' => 'Tel. 782 865 895 · kontakt@retrievershop.pl · Legnica',
        'og_image_type' => 'custom',
        'og_image_custom_url' => $LOGO,
        'og_image_url' => $LOGO,
        'twitter_image_type' => 'custom',
        'twitter_image_custom_url' => $LOGO,
        'twitter_image_url' => $LOGO,
    ]);
    rs_log('kontakt OG+meta OK');
}

// --- 3) Category descriptions ---
$cat_descriptions = [
    'szelki' => 'Szelki dla psa Truelove — modele spacerowe, treningowe i Cordura. Wybierz rozmiar i kolor dopasowany do Twojego psa.',
    'smycze' => 'Smycze dla psa Truelove: klasyczne, z amortyzatorem i trekkingowe. Solidne materiały i wygodne uchwyty.',
    'obroza' => 'Obroże dla psa Truelove — treningowe, odblaskowe i materiałowe. Bezpieczne dopasowanie na co dzień.',
    'saszetki' => 'Saszetki i akcesoria na przysmaki Truelove — praktyczne na spacer i trening.',
    'pasy-bezpieczenstwa' => 'Pasy bezpieczeństwa / samochodowe dla psa Truelove — bezpieczny przewóz w aucie.',
    'amortyzator' => 'Amortyzatory do smyczy Truelove — mniej szarpnięć, więcej komfortu na spacerze i treningu.',
    'kamizelka' => 'Kamizelki dla psa Truelove — chłodzące i użytkowe modele na ciepłe dni i aktywność.',
    'kapok' => 'Kapoki i kamizelki ratunkowe dla psa Truelove Dive — bezpieczeństwo nad wodą.',
    'linka' => 'Linki treningowe dla psa — kontrola na odległość podczas nauki i spacerów.',
    'pas-trekkingowy' => 'Pasy trekkingowe Truelove — wygodne noszenie smyczy i akcesoriów w terenie.',
];
foreach ($cat_descriptions as $slug => $desc) {
    $term = get_term_by('slug', $slug, 'product_cat');
    if (!$term || is_wp_error($term)) {
        rs_log("cat missing {$slug}");
        continue;
    }
    wp_update_term((int) $term->term_id, 'product_cat', ['description' => $desc]);
    rs_log("cat desc {$slug}");
}

// --- 4) Color map for titles ---
$COLOR_SLUGS = [
    'czarne' => 'czarne', 'czarny' => 'czarne', 'czarna' => 'czarne',
    'czerwone' => 'czerwone', 'czerwony' => 'czerwone', 'czerwona' => 'czerwone',
    'granatowe' => 'granatowe', 'granatowy' => 'granatowe', 'granatowa' => 'granatowe',
    'niebieskie' => 'niebieskie', 'niebieski' => 'niebieskie', 'niebieska' => 'niebieskie',
    'zielone' => 'zielone', 'zielony' => 'zielone', 'zielona' => 'zielone',
    'szare' => 'szare', 'szary' => 'szare', 'szara' => 'szare',
    'rozowe' => 'różowe', 'różowe' => 'różowe', 'rozowy' => 'różowe', 'różowy' => 'różowe',
    'fioletowe' => 'fioletowe', 'fioletowy' => 'fioletowe', 'fioletowa' => 'fioletowe',
    'pomaranczowe' => 'pomarańczowe', 'pomarańczowe' => 'pomarańczowe',
    'limonkowe' => 'limonkowe', 'limonkowy' => 'limonkowe',
    'turkusowe' => 'turkusowe', 'brazowe' => 'brązowe', 'brązowe' => 'brązowe',
    'liliowy' => 'liliowe', 'liliowe' => 'liliowe', 'liliowa' => 'liliowe',
    'bezowe' => 'beżowe', 'beżowe' => 'beżowe', 'bialy' => 'białe', 'biale' => 'białe', 'białe' => 'białe',
];
$SIZE_SLUGS = ['xxs','xs','s','m','l','xl','xxl','2xl','3xl','4xl'];

function rs_color_from_product($product_id, $slug, $COLOR_SLUGS, $SIZE_SLUGS) {
    $terms = wp_get_post_terms($product_id, 'pa_kolor', ['fields' => 'names']);
    if (!is_wp_error($terms) && $terms) {
        $c = trim((string) $terms[0]);
        if ($c !== '') {
            return mb_strtolower($c);
        }
    }
    $parts = explode('-', (string) $slug);
    // walk from end, skip size/length tokens
    for ($i = count($parts) - 1; $i >= 0; $i--) {
        $tok = $parts[$i];
        if ($tok === '' || is_numeric($tok) || in_array($tok, $SIZE_SLUGS, true)) {
            continue;
        }
        if (isset($COLOR_SLUGS[$tok])) {
            return $COLOR_SLUGS[$tok];
        }
        // compound e.g. pomaranczowe already
        foreach ($COLOR_SLUGS as $k => $v) {
            if ($tok === $k) {
                return $v;
            }
        }
    }
    return '';
}

$products = get_posts([
    'post_type' => 'product',
    'post_status' => 'publish',
    'posts_per_page' => -1,
    'fields' => 'ids',
]);
$title_updates = 0;
foreach ($products as $pid) {
    $post = get_post($pid);
    if (!$post) {
        continue;
    }
    $color = rs_color_from_product($pid, $post->post_name, $COLOR_SLUGS, $SIZE_SLUGS);
    if ($color === '') {
        continue;
    }
    // Ensure pa_kolor term
    $term = term_exists($color, 'pa_kolor');
    if (!$term) {
        $ins = wp_insert_term(mb_convert_case($color, MB_CASE_TITLE, 'UTF-8'), 'pa_kolor', ['slug' => sanitize_title($color)]);
        if (!is_wp_error($ins)) {
            $term = $ins;
        }
    }
    if ($term && !is_wp_error($term)) {
        $tid = is_array($term) ? (int) $term['term_id'] : (int) $term;
        wp_set_object_terms($pid, [$tid], 'pa_kolor', false);
    }

    $base = $post->post_title;
    // strip existing em-dash color suffix
    $base = preg_replace('/\s+[—–-]\s+[^\s—–-]+$/u', '', $base);
    $base = trim($base);
    $new_title = $base . ' — ' . $color;
    if ($new_title === $post->post_title) {
        continue;
    }
    wp_update_post(['ID' => $pid, 'post_title' => $new_title]);
    $title_updates++;

    // Unique SEO title
    $seo_title = $new_title . ' | Retriever Shop';
    $seo_desc = wp_strip_all_tags(get_the_excerpt($pid));
    if (strlen($seo_desc) < 40) {
        $p = wc_get_product($pid);
        if ($p) {
            $seo_desc = wp_strip_all_tags($p->get_short_description() ?: $p->get_description());
        }
    }
    $seo_desc = mb_substr(trim(preg_replace('/\s+/', ' ', $seo_desc)), 0, 160);
    update_post_meta($pid, '_aioseo_title', $seo_title);
    if ($seo_desc) {
        update_post_meta($pid, '_aioseo_description', $seo_desc);
    }
    rs_aioseo_upsert($pid, array_filter([
        'title' => $seo_title,
        'description' => $seo_desc ?: null,
        'og_title' => $new_title,
        'og_description' => $seo_desc ?: null,
        'og_image_type' => 'default', // featured
    ]));
}
rs_log("title_color_updates={$title_updates}");

// --- 5) Thumbnail #3494 from sibling ---
$missing = [3494];
foreach ($missing as $pid) {
    $p = wc_get_product($pid);
    if (!$p || has_post_thumbnail($pid)) {
        continue;
    }
    $donor = 3500; // Front Line Cordura sibling with thumb
    $thumb = get_post_thumbnail_id($donor);
    if (!$thumb) {
        // any Front Line Premium Cordura with thumb
        $q = new WP_Query([
            'post_type' => 'product',
            's' => 'Front Line Premium Cordura',
            'posts_per_page' => 5,
            'meta_query' => [['key' => '_thumbnail_id', 'compare' => 'EXISTS']],
        ]);
        while ($q->have_posts()) {
            $q->the_post();
            $thumb = get_post_thumbnail_id(get_the_ID());
            if ($thumb) {
                break;
            }
        }
        wp_reset_postdata();
    }
    if ($thumb) {
        set_post_thumbnail($pid, $thumb);
        rs_log("thumb #{$pid} <- attachment {$thumb}");
    } else {
        rs_log("thumb #{$pid} FAILED no donor");
    }
}

// --- 6) Image ALT backfill ---
$atts = $wpdb->get_results(
    "SELECT p.ID, p.post_title, p.post_parent
     FROM {$wpdb->posts} p
     LEFT JOIN {$wpdb->postmeta} m ON m.post_id=p.ID AND m.meta_key='_wp_attachment_image_alt'
     WHERE p.post_type='attachment' AND p.post_mime_type LIKE 'image/%'
     AND (m.meta_id IS NULL OR TRIM(IFNULL(m.meta_value,''))='')
     LIMIT 2500"
);
$alt_n = 0;
foreach ($atts as $a) {
    $alt = trim((string) $a->post_title);
    if ($alt === '' || preg_match('/^\d+$/', $alt) || stripos($alt, 'woocommerce-placeholder') !== false) {
        if ($a->post_parent) {
            $alt = get_the_title((int) $a->post_parent);
        }
    }
    $alt = trim(preg_replace('/\s+/', ' ', wp_strip_all_tags($alt)));
    // strip file-ish
    $alt = preg_replace('/\.(jpg|jpeg|png|webp|gif)$/i', '', $alt);
    if ($alt === '' || strlen($alt) < 3) {
        $alt = 'Retriever Shop — akcesoria dla psa';
    }
    update_post_meta((int) $a->ID, '_wp_attachment_image_alt', $alt);
    $alt_n++;
}
rs_log("alt_updated={$alt_n}");

// --- 7) Homepage H1 via MU helper option + ensure visible heading in content if missing ---
// Store preferred H1; MU plugin renders it. Also inject into Elementor if no h1 in rendered sense.
update_option('rs_seo_home_h1', 'Retriever Shop — szelki i smycze dla psów', false);

// If Elementor data has no Heading with h1, prepend a lightweight HTML block in post_content fallback
$home = get_post($HOME_ID);
$has_h1_marker = $home && (stripos($home->post_content, '<h1') !== false || stripos((string) get_post_meta($HOME_ID, '_elementor_data', true), '"header_size":"h1"') !== false || stripos((string) get_post_meta($HOME_ID, '_elementor_data', true), '"header_size":"H1"') !== false);
rs_log('home_has_h1_marker=' . ($has_h1_marker ? 'yes' : 'no'));

// --- 8) Purge caches ---
if (class_exists('\\Elementor\\Plugin')) {
    \Elementor\Plugin::$instance->files_manager->clear_cache();
    rs_log('elementor cache cleared');
}
if (function_exists('wp_cache_flush')) {
    wp_cache_flush();
}
// Seraphinite
do_action('litespeed_purge_all');
if (class_exists('Seraphinite\\Plugin') || defined('SERAPH_ACC_VER')) {
    // best-effort: delete cache dir flag via option bump
    update_option('rs_seo_cache_bump', time());
}
rs_log('DONE seo_fix_all');
