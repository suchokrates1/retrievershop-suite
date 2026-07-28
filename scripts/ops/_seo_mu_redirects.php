<?php
/**
 * Plugin Name: Retriever SEO slug redirects
 * Description: 301 for renamed typo product slugs (no Redirection plugin).
 */
/** Drop stale AIOSEO RSS sitemap line from robots.txt (keep sitemap.xml only). */
add_filter('robots_txt', function ($output, $public) {
    if (!$public) {
        return $output;
    }
    $lines = preg_split("/\r\n|\n|\r/", (string) $output);
    $out = [];
    foreach ($lines as $line) {
        if (stripos($line, 'sitemap.rss') !== false) {
            continue;
        }
        $out[] = $line;
    }
    return implode("\n", $out) . "\n";
}, 10001, 2);

/** Avoid long edge-cache of robots.txt (Cloudflare was serving stale RSS line). */
add_action('do_robotstxt', function () {
    if (!headers_sent()) {
        header('Cache-Control: no-store, max-age=0');
        header('CDN-Cache-Control: no-store');
    }
}, 0);

add_action('template_redirect', function () {
    if (is_admin()) {
        return;
    }
    $uri = trim(parse_url($_SERVER['REQUEST_URI'] ?? '', PHP_URL_PATH), '/');
    $map = [
        'produkt/szelki-dla-psa-trelove-front-line-premium-xs-czarne' => '/produkt/szelki-dla-psa-truelove-front-line-premium-czarne/',
        'produkt/szelki-dla-psa-truelove-fronr-line-premium-czerwonw' => '/produkt/szelki-dla-psa-truelove-front-line-premium-czerwone/',
        'produkt/szelki-dla-psa-truelve-front-line-ptemium-s-granatowe' => '/produkt/szelki-dla-psa-truelove-front-line-premium-granatowe/',
        // Canonical returns / trust pages
        'zwroty-2' => '/zwroty/',
        // Old color-parent duplicates (now private) → canonical parents
        'produkt/szelki-dla-psa-truelove-adventure-dog-blekitne' => '/produkt/szelki-dla-psa-truelove-adventure-dog/',
        'produkt/szelki-dla-psa-truelove-blossom-premium-czerwono-biale' => '/produkt/szelki-dla-psa-truelove-blossom/',
        'produkt/szelki-dla-psa-truelove-blossom-czerwono-biale' => '/produkt/szelki-dla-psa-truelove-blossom/',
        'produkt/szelki-dla-psa-truelove-blossom-premium-granatowo-biale' => '/produkt/szelki-dla-psa-truelove-blossom/',
        'produkt/szelki-dla-psa-truelove-front-line-premium-brazowe' => '/produkt/szelki-dla-psa-truelove-front-line-premium/',
        'produkt/szelki-dla-psa-truelove-lumen-pomarannczowe' => '/produkt/szelki-dla-psa-truelove-lumen/',
        'produkt/szelki-dla-psa-truelove-lumen-pomaranczowe' => '/produkt/szelki-dla-psa-truelove-lumen/',
    ];
    if (isset($map[$uri])) {
        wp_redirect(home_url($map[$uri]), 301);
        exit;
    }
}, 0);
