<?php
/**
 * Apply Retriever Shop UI redesign after appearance backup.
 * - Disable frontend dark mode
 * - Refine Blocksy palette + typography
 * - Shop sidebar filters (Filter Everything)
 * - Homepage Woo shortcodes
 * - PDP / cart trust copy via Blocksy + page content
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

function rs_log($msg) {
    echo $msg . "\n";
}

// ---------- 1) Dark mode OFF on frontend ----------
update_option('wp_dark_mode_frontend_enabled', '0');
update_option('wp_dark_mode_floating_switch_enabled', '0');
rs_log('dark_mode_frontend_disabled');

// ---------- 2) Blocksy design tokens ----------
$stylesheet = get_option('stylesheet') ?: 'blocksy-child';
$mod_key = 'theme_mods_' . $stylesheet;
$mods = get_option($mod_key);
if (!is_array($mods)) {
    $mods = get_option('theme_mods_blocksy') ?: [];
}

// Warm outdoor brand: deep teal + terracotta accent (existing DNA, refined)
$mods['colorPalette'] = [
    'color1' => ['color' => '#C45C3E'], // accent / price / CTA
    'color2' => ['color' => '#9E4A32'],
    'color3' => ['color' => '#2F4F4F'], // body / headings support
    'color4' => ['color' => '#1A3333'], // dark
    'color5' => ['color' => '#E6E2DC'],
    'color6' => ['color' => '#F3F0EB'],
    'color7' => ['color' => '#FAF8F5'],
    'color8' => ['color' => '#FFFFFF'],
];

// Typography: Poppins UI + IBM Plex Serif display (already in use)
$mods['rootTypography'] = [
    'family' => 'Poppins',
    'variation' => 'n4',
    'size' => '16px',
    'line-height' => '1.65',
    'letter-spacing' => '0em',
    'text-transform' => 'none',
    'text-decoration' => 'none',
];
$mods['h1Typography'] = [
    'family' => 'IBM Plex Serif',
    'variation' => 'n7',
    'size' => '42px',
    'line-height' => '1.25',
    'letter-spacing' => '-0.01em',
    'text-transform' => 'none',
    'text-decoration' => 'none',
];
$mods['h2Typography'] = [
    'family' => 'IBM Plex Serif',
    'variation' => 'n7',
    'size' => '32px',
    'line-height' => '1.3',
    'letter-spacing' => '-0.01em',
    'text-transform' => 'none',
    'text-decoration' => 'none',
];
$mods['buttonMinHeight'] = 48;
$mods['buttonRadius'] = [
    'top' => '6px', 'bottom' => '6px', 'left' => '6px', 'right' => '6px', 'linked' => true,
];
$mods['cardProductRadius'] = [
    'top' => '8px', 'bottom' => '8px', 'left' => '8px', 'right' => '8px', 'linked' => true,
];
$mods['cardProductTitleFont'] = [
    'family' => 'Poppins',
    'variation' => 'n6',
    'size' => '16px',
    'line-height' => '1.35',
    'letter-spacing' => '0em',
    'text-transform' => 'none',
    'text-decoration' => 'none',
];

// Shop / archive
$mods['woo_categories_has_sidebar'] = 'yes';
$mods['woo_categories_sidebar_position'] = 'left';
$mods['has_shop_sort'] = 'yes';
$mods['shop_columns'] = [
    'desktop' => 3,
    'tablet' => 2,
    'mobile' => 2,
];
$mods['woocommerce_catalog_columns'] = 3;

// Single product: show title, sticky gallery/summary
$mods['has_product_single_title'] = 'yes';
$mods['has_product_sticky_gallery'] = 'yes';
$mods['has_product_sticky_summary'] = 'yes';
$mods['has_product_action_button'] = 'yes';
$mods['productGalleryWidth'] = 52;

update_option($mod_key, $mods);
// Also mirror to parent key if child empty historically
update_option('theme_mods_blocksy-child', $mods);
rs_log('blocksy_theme_mods_updated');

// Custom CSS polish (child theme + customizer)
$custom_css = <<<'CSS'
/* Retriever Shop UI v1 — applied after appearance backup */
:root {
  --rs-accent: #C45C3E;
  --rs-ink: #1A3333;
  --rs-muted: #5A6B6B;
  --rs-sand: #F3F0EB;
}
body {
  color: var(--rs-ink);
}
.button, .ct-button, button.single_add_to_cart_button, .checkout-button, .woocommerce a.button.alt {
  border-radius: 6px !important;
  letter-spacing: 0.02em;
}
.woocommerce ul.products li.product .woocommerce-loop-product__title {
  font-weight: 600;
  font-size: 15px;
  line-height: 1.35;
}
.woocommerce div.product p.price, .woocommerce ul.products li.product .price {
  color: var(--rs-accent);
  font-weight: 600;
}
.woocommerce-info, .woocommerce-message {
  border-top-color: var(--rs-accent);
}
.rs-trust-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 12px;
  margin: 18px 0 8px;
  padding: 14px 16px;
  background: var(--rs-sand);
  border-radius: 8px;
  font-size: 13px;
  color: var(--rs-muted);
}
.rs-trust-row strong { color: var(--rs-ink); display: block; font-size: 13px; margin-bottom: 2px; }
.rs-size-guide {
  margin: 20px 0;
  padding: 16px;
  border: 1px solid #e5e1da;
  border-radius: 8px;
  background: #fff;
}
.rs-size-guide h3 { margin: 0 0 10px; font-size: 18px; }
.rs-size-guide table { width: 100%; border-collapse: collapse; font-size: 13px; }
.rs-size-guide th, .rs-size-guide td { border-bottom: 1px solid #eee; padding: 8px 6px; text-align: left; }
.wpc-filters-widget-wrapper, .wpc-filters-section { --wpc-primary-color: #C45C3E; }
CSS;

$existing = wp_get_custom_css();
if (strpos($existing, 'Retriever Shop UI v1') === false) {
    wp_update_custom_css_post(trim($existing . "\n\n" . $custom_css));
    rs_log('custom_css_appended');
} else {
    // Replace previous v1 block
    $updated = preg_replace('/\/\* Retriever Shop UI v1[\s\S]*$/m', trim($custom_css), $existing);
    if ($updated && $updated !== $existing) {
        wp_update_custom_css_post($updated);
        rs_log('custom_css_replaced');
    } else {
        wp_update_custom_css_post(trim($custom_css));
        rs_log('custom_css_set');
    }
}

// ---------- 3) Filter Everything: Rozmiar / Kolor / Marka / Seria ----------
function rs_fe_field_payload($e_name, $title, $view = 'checkboxes') {
    return [
        'entity' => 'taxonomy',
        'e_name' => $e_name,
        'view' => $view,
        'date_type' => 'date',
        'show_term_names' => 'yes',
        'dropdown_label' => '',
        'date_format' => 'Y-m-d',
        'logic' => 'or',
        'orderby' => 'default',
        'in_path' => 'yes',
        'include' => 'no',
        'range_slider' => 'yes',
        'step' => '1',
        'parent_filter' => '-1',
        'min_num_label' => '',
        'max_num_label' => '',
        'tooltip' => '',
        'show_chips' => 'yes',
        'acf_fields' => '',
        'collapse' => 'no',
        'hierarchy' => 'no',
        'search' => 'no',
        'hide_until_parent' => 'no',
        'more_less' => 'no',
    ];
}

$set_id = 2739;
if (!get_post($set_id)) {
    $set_id = wp_insert_post([
        'post_type' => 'filter-set',
        'post_title' => 'Pasek boczny sklepu',
        'post_status' => 'publish',
    ]);
    update_post_meta($set_id, 'wpc_filter_set_post_type', 'product');
    rs_log("created_filter_set #{$set_id}");
}

$desired = [
    'product_cat' => ['Kategorie', 'checkboxes'],
    'pa_rozmiar' => ['Rozmiar', 'checkboxes'],
    'pa_kolor' => ['Kolor', 'checkboxes'],
    'pa_marka' => ['Marka', 'checkboxes'],
    'pa_seria' => ['Seria', 'checkboxes'],
];

$existing_fields = get_posts([
    'post_type' => 'filter-field',
    'post_parent' => $set_id,
    'posts_per_page' => -1,
    'post_status' => 'any',
]);
$by_ename = [];
foreach ($existing_fields as $f) {
    $data = @unserialize($f->post_content);
    if (is_array($data) && !empty($data['e_name'])) {
        $by_ename[$data['e_name']] = $f->ID;
    }
}

foreach ($desired as $ename => [$title, $view]) {
    $payload = rs_fe_field_payload($ename, $title, $view);
    $content = serialize($payload);
    $excerpt = 'taxonomy_' . $ename;
    if (isset($by_ename[$ename])) {
        wp_update_post([
            'ID' => $by_ename[$ename],
            'post_title' => $title,
            'post_content' => $content,
            'post_excerpt' => $excerpt,
            'post_status' => 'publish',
        ]);
        rs_log("updated_filter {$ename} #{$by_ename[$ename]}");
    } else {
        $fid = wp_insert_post([
            'post_type' => 'filter-field',
            'post_parent' => $set_id,
            'post_title' => $title,
            'post_content' => $content,
            'post_excerpt' => $excerpt,
            'post_status' => 'publish',
            'post_name' => sanitize_title($ename),
        ]);
        rs_log("created_filter {$ename} #{$fid}");
    }
}

// Filter settings polish
$fs = get_option('wpc_filter_settings');
if (!is_array($fs)) {
    $fs = [];
}
$fs['primary_color'] = '#C45C3E';
$fs['posts_container'] = 'ul.products';
$fs['try_move_to_top_sidebar'] = 'on';
update_option('wpc_filter_settings', $fs);
rs_log('wpc_filter_settings_updated');

// Ensure Filters widget in shop sidebar
$sidebars = wp_get_sidebars_widgets();
if (!is_array($sidebars)) {
    $sidebars = [];
}
$shop_sidebar_keys = array_filter(array_keys($sidebars), function ($k) {
    return stripos($k, 'sidebar') !== false || stripos($k, 'woo') !== false || stripos($k, 'shop') !== false;
});
rs_log('sidebars=' . implode(',', array_keys($sidebars)));

// Register a text widget with shortcode if Filters widget class exists
if (class_exists('FilterEverything\\Admin\\Widgets\\FiltersWidget') || class_exists('WPC_Filters_Widget')) {
    // Prefer shortcode in a custom HTML widget for reliability
}
$widget_text = get_option('widget_text', []);
if (!is_array($widget_text)) {
    $widget_text = [];
}
$wid = 901;
$widget_text[$wid] = [
    'title' => 'Filtry',
    'text' => '[fe_widget id="' . (int) $set_id . '" title=""]',
    'filter' => false,
];
$widget_text['_multiwidget'] = 1;
update_option('widget_text', $widget_text);

// Put widget into first suitable sidebar if empty-ish
$target_sidebar = null;
foreach (['sidebar-1', 'woo-sidebar', 'shop-sidebar', 'ct-dynamic-sidebar-1'] as $cand) {
    if (isset($sidebars[$cand])) {
        $target_sidebar = $cand;
        break;
    }
}
if (!$target_sidebar) {
    $keys = array_keys($sidebars);
    $target_sidebar = $keys[0] ?? 'sidebar-1';
    if (!isset($sidebars[$target_sidebar])) {
        $sidebars[$target_sidebar] = [];
    }
}
$widget_id = 'text-' . $wid;
$already = false;
foreach ($sidebars as $sb => $widgets) {
    if (is_array($widgets) && in_array($widget_id, $widgets, true)) {
        $already = true;
        break;
    }
}
if (!$already) {
    $sidebars[$target_sidebar][] = $widget_id;
    wp_set_sidebars_widgets($sidebars);
    rs_log("filters_widget_added_to {$target_sidebar}");
} else {
    rs_log('filters_widget_already_present');
}

// ---------- 4) Homepage shortcodes ----------
$HOME_ID = (int) get_option('page_on_front') ?: 595;
$data = get_post_meta($HOME_ID, '_elementor_data', true);
if ($data) {
    $orig = $data;
    // Featured / newest in-stock oriented
    $data = preg_replace(
        '/\[products[^\]]*visibility=\\\"featured\\\"[^\]]*\]/',
        '[products limit="6" columns="3" visibility="featured" orderby="menu_order"]',
        $data
    );
    $data = str_replace(
        '[products limit=\"3\" columns=\"3\" visibility=\"featured\"]',
        '[products limit="6" columns="3" category="szelki,smycze,obroza" orderby="date" order="DESC" visibility="visible"]',
        $data
    );
    // If second products shortcode still generic
    if (substr_count($data, '[products') < 2) {
        rs_log('homepage_products_shortcodes_count_low');
    }
    if ($data !== $orig) {
        update_post_meta($HOME_ID, '_elementor_data', wp_slash($data));
        rs_log('homepage_elementor_updated');
    } else {
        rs_log('homepage_elementor_unchanged');
    }
}

// ---------- 5) Size guide + trust on single product via woocommerce hooks in child theme ----------
$child_functions = ABSPATH . 'wp-content/themes/blocksy-child/functions.php';
$hook_snippet = <<<'PHP'

/**
 * Retriever Shop UI v1 — PDP trust + size guide
 */
add_action('woocommerce_single_product_summary', function () {
    echo '<div class="rs-trust-row">';
    echo '<div><strong>Wysyłka</strong>Szybka wysyłka z Legnicy</div>';
    echo '<div><strong>Zwroty</strong>14 dni na odstąpienie</div>';
    echo '<div><strong>Kontakt</strong><a href="tel:+48782865895">782 865 895</a></div>';
    echo '<div><strong>Płatności</strong>BLIK, przelew, karta</div>';
    echo '</div>';
}, 35);

add_action('woocommerce_after_single_product_summary', function () {
    if (!is_product()) {
        return;
    }
    global $product;
    if (!$product) {
        return;
    }
    $name = mb_strtolower($product->get_name());
    if (strpos($name, 'szelk') === false && strpos($name, 'obroż') === false && strpos($name, 'obroz') === false) {
        return;
    }
    echo '<div class="rs-size-guide"><h3>Tabela rozmiarów (orientacyjna)</h3>';
    echo '<table><thead><tr><th>Rozmiar</th><th>Obwód klatki</th><th>Waga psa (orient.)</th></tr></thead><tbody>';
    $rows = [
        ['XS', '30–40 cm', 'do ~5 kg'],
        ['S', '40–50 cm', '~5–10 kg'],
        ['M', '50–65 cm', '~10–20 kg'],
        ['L', '65–80 cm', '~20–35 kg'],
        ['XL', '80–95 cm', '~35–45 kg'],
        ['2XL', '95–110 cm', '45+ kg'],
    ];
    foreach ($rows as [$s, $o, $w]) {
        echo '<tr><td>' . esc_html($s) . '</td><td>' . esc_html($o) . '</td><td>' . esc_html($w) . '</td></tr>';
    }
    echo '</tbody></table>';
    echo '<p style="margin:10px 0 0;font-size:13px;color:#5A6B6B;">Zawsze porównaj wymiary z tabelą producenta na karcie produktu / w opisie.</p></div>';
}, 8);

add_action('woocommerce_proceed_to_checkout', function () {
    echo '<div class="rs-trust-row" style="margin-top:12px">';
    echo '<div><strong>Bezpieczne płatności</strong>BLIK / karta / przelew</div>';
    echo '<div><strong>InPost</strong>Paczkomaty i kurier</div>';
    echo '<div><strong>Pytania?</strong><a href="tel:+48782865895">782 865 895</a></div>';
    echo '</div>';
}, 20);
PHP;

if (file_exists($child_functions)) {
    $fn = file_get_contents($child_functions);
    if (strpos($fn, 'Retriever Shop UI v1') === false) {
        file_put_contents($child_functions, rtrim($fn) . "\n" . $hook_snippet . "\n");
        rs_log('child_functions_hooks_added');
    } else {
        // Replace from marker to EOF-ish — rewrite by cutting old block
        $fn2 = preg_replace('/\n\/\*\*\s*\n \* Retriever Shop UI v1[\s\S]*$/m', "\n" . $hook_snippet . "\n", $fn);
        file_put_contents($child_functions, $fn2 ?: (rtrim($fn) . "\n" . $hook_snippet));
        rs_log('child_functions_hooks_refreshed');
    }
} else {
    file_put_contents($child_functions, "<?php\n" . $hook_snippet . "\n");
    rs_log('child_functions_created');
}

// Catalog defaults
update_option('woocommerce_default_catalog_orderby', 'popularity');
update_option('woocommerce_catalog_columns', 3);
update_option('woocommerce_catalog_rows', 4);

if (class_exists('\\Elementor\\Plugin')) {
    \Elementor\Plugin::$instance->files_manager->clear_cache();
    rs_log('elementor_cache_cleared');
}

// Flush Blocksy dynamic CSS by touching option
if (function_exists('blocksy_get_theme_preferences')) {
    rs_log('blocksy_detected');
}
rs_log('DONE ui_apply');
