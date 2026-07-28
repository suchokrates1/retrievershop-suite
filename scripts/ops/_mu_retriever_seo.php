<?php
/**
 * Plugin Name: Retriever SEO
 * Description: Slug 301 redirects (static + option rs_seo_slug_redirects) + homepage H1 (hero) + OG safety.
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
        'produkt/szelki-dla-psa-trelove-front-line-premium-xs-czarne' => '/produkt/szelki-dla-psa-truelove-front-line-premium/',
        'produkt/szelki-dla-psa-truelove-fronr-line-premium-czerwonw' => '/produkt/szelki-dla-psa-truelove-front-line-premium/',
        'produkt/szelki-dla-psa-truelve-front-line-ptemium-s-granatowe' => '/produkt/szelki-dla-psa-truelove-front-line-premium/',
    ];
    $extra = get_option('rs_seo_slug_redirects', []);
    if (is_string($extra)) {
        $decoded = json_decode($extra, true);
        if (is_array($decoded)) {
            $extra = $decoded;
        } else {
            $extra = [];
        }
    }
    if (is_array($extra)) {
        $map = array_merge($map, $extra);
    }
    if (isset($map[$uri])) {
        wp_redirect(home_url($map[$uri]), 301);
        exit;
    }
}, 0);

/**
 * Homepage H1 = Elementor hero "Łączymy pasję do zwierząt z jakością".
 * Drops legacy injected H1; promotes H2/H3 hero to H1 if Elementor still emits it.
 */
add_action('template_redirect', function () {
    if (!is_front_page() || is_admin()) {
        return;
    }
    ob_start(function ($html) {
        if (!is_string($html) || $html === '') {
            return $html;
        }
        $html = preg_replace(
            '#<div class="rs-seo-home-h1-wrap"[^>]*>.*?</div>#is',
            '',
            $html,
            1
        );
        $html = preg_replace_callback(
            '#<(h[23])(\s+class="[^"]*elementor-heading-title[^"]*"[^>]*)>(\s*Łączymy pasję do zwierząt z jakością\s*)</\1>#u',
            function ($m) {
                return '<h1' . $m[2] . '>' . $m[3] . '</h1>';
            },
            $html,
            1
        );
        return $html;
    });
}, 0);

/**
 * Prefer featured image / logo over expired Facebook CDN URLs in social tags.
 */
$rs_seo_social_image = static function (array $tags, array $keys): array {
    $logo = 'https://retrievershop.pl/wp-content/uploads/2024/08/retriver-2.png';
    $preferred = $logo;
    if ((is_singular(['product', 'post']) || is_page()) && has_post_thumbnail()) {
        $preferred = get_the_post_thumbnail_url(null, 'full') ?: $logo;
    }
    foreach ($keys as $key) {
        $val = '';
        if (!empty($tags[$key])) {
            $val = is_array($tags[$key]) ? (string) reset($tags[$key]) : (string) $tags[$key];
        }
        $bad = $val === ''
            || stripos($val, 'fbcdn') !== false
            || stripos($val, 'facebook.com') !== false;
        if ($bad) {
            $tags[$key] = $preferred;
        }
    }
    return $tags;
};

add_filter('aioseo_facebook_tags', function ($tags) use ($rs_seo_social_image) {
    if (!is_array($tags)) {
        return $tags;
    }
    return $rs_seo_social_image($tags, ['og:image', 'og:image:secure_url']);
}, 50);

add_filter('aioseo_twitter_tags', function ($tags) use ($rs_seo_social_image) {
    if (!is_array($tags)) {
        return $tags;
    }
    return $rs_seo_social_image($tags, ['twitter:image', 'twitter:image:src']);
}, 50);
