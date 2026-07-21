<?php
/**
 * Plugin Name: Retriever SEO
 * Description: Slug 301 redirects + homepage H1 + OG safety helpers.
 */
if (!defined('ABSPATH')) {
    exit;
}

add_action('template_redirect', function () {
    if (is_admin()) {
        return;
    }
    $uri = trim((string) parse_url($_SERVER['REQUEST_URI'] ?? '', PHP_URL_PATH), '/');
    $map = [
        'produkt/szelki-dla-psa-trelove-front-line-premium-xs-czarne' => '/produkt/szelki-dla-psa-truelove-front-line-premium-czarne/',
        'produkt/szelki-dla-psa-truelove-fronr-line-premium-czerwonw' => '/produkt/szelki-dla-psa-truelove-front-line-premium-czerwone/',
        'produkt/szelki-dla-psa-truelve-front-line-ptemium-s-granatowe' => '/produkt/szelki-dla-psa-truelove-front-line-premium-granatowe/',
    ];
    if (isset($map[$uri])) {
        wp_redirect(home_url($map[$uri]), 301);
        exit;
    }
}, 0);

// H1 na homepage (Elementor często nie wystawia h1)
add_action('wp_body_open', function () {
    if (!is_front_page()) {
        return;
    }
    $h1 = (string) get_option('rs_seo_home_h1', 'Retriever Shop — szelki i smycze dla psów');
    echo '<div class="rs-seo-home-h1-wrap" style="max-width:1100px;margin:0 auto;padding:18px 20px 0;">'
        . '<h1 class="rs-seo-home-h1" style="margin:0;font-size:clamp(1.35rem,2.5vw,1.85rem);line-height:1.25;color:#1a1a2e;font-weight:700;">'
        . esc_html($h1)
        . '</h1></div>';
}, 5);

// Prefer featured image for product OG; never emit fbcdn via late filter if somehow injected
add_filter('aioseo_facebook_tags', function ($tags) {
    if (!is_array($tags)) {
        return $tags;
    }
    $logo = 'https://retrievershop.pl/wp-content/uploads/2024/08/retriver-2.png';
    foreach (['og:image', 'og:image:secure_url'] as $key) {
        if (empty($tags[$key])) {
            continue;
        }
        $val = is_array($tags[$key]) ? (string) reset($tags[$key]) : (string) $tags[$key];
        if (stripos($val, 'fbcdn') !== false || stripos($val, 'facebook.com') !== false) {
            if (is_singular('product') && has_post_thumbnail()) {
                $tags[$key] = get_the_post_thumbnail_url(null, 'full') ?: $logo;
            } else {
                $tags[$key] = $logo;
            }
        }
    }
    return $tags;
}, 50);
