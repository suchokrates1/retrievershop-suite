<?php
/**
 * Plugin Name: Retriever SEO slug redirects
 * Description: 301 for renamed typo product slugs (no Redirection plugin).
 */
add_action('template_redirect', function () {
    if (is_admin()) {
        return;
    }
    $uri = trim(parse_url($_SERVER['REQUEST_URI'] ?? '', PHP_URL_PATH), '/');
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
