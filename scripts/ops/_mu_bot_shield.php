<?php
/**
 * Plugin Name: Retriever Bot Shield
 * Description: Stop AI crawlers from melting RPI on Filter Everything faceted URLs.
 */
if (!defined('ABSPATH')) {
    exit;
}

/**
 * Hard-block abusive AI crawlers early (before heavy WP/Woo bootstrap finishes).
 * These bots were hammering /seria|/kolor|/rozmiar|/produkty filter permutations.
 */
add_action('muplugins_loaded', static function () {
    $ua = (string) ($_SERVER['HTTP_USER_AGENT'] ?? '');
    if ($ua === '') {
        return;
    }
    // meta-externalagent = Meta AI crawler (NOT facebookexternalhit used for OG previews).
    // Was melting WP hourly (~12k req/2h) on Filter Everything facet permutations → 503 for Uptime.
    if (!preg_match('/GPTBot|ChatGPT-User|ClaudeBot|anthropic-ai|Claude-Web|CCBot|Bytespider|Amazonbot|PetalBot|Diffbot|DataForSeoBot|SemiBot|meta-externalagent|FacebookBot/i', $ua)) {
        return;
    }

    // Allow homepage + sitemap only would still spawn cron; block entirely for these UAs.
    status_header(429);
    header('Retry-After: 86400');
    header('Content-Type: text/plain; charset=UTF-8');
    header('Cache-Control: no-store');
    echo "Too Many Requests\n";
    exit;
}, 0);

/**
 * Facet-permutation spam from unknown bots (not browsers, not Google/Bing/OG).
 * Real shoppers keep normal browser UAs; Meta AI was hitting /linka/?a&b&c&seria=…
 */
add_action('muplugins_loaded', static function () {
    $uri = (string) ($_SERVER['REQUEST_URI'] ?? '');
    if ($uri === '' || strpos($uri, '?') === false) {
        return;
    }
    if (!preg_match('#/(kategoria-produktu|seria|kolor|rozmiar|produkty)/#i', $uri)) {
        return;
    }
    $ua = (string) ($_SERVER['HTTP_USER_AGENT'] ?? '');
    if ($ua === '') {
        return;
    }
    // Browsers / major engines / FB share preview — allow.
    if (preg_match('/Mozilla\/|Googlebot|Google-InspectionTool|bingbot|Applebot|DuckDuckBot|YandexBot|facebookexternalhit|Facebot/i', $ua)) {
        return;
    }
    $q = (string) (parse_url($uri, PHP_URL_QUERY) ?? '');
    if ($q === '') {
        return;
    }
    $amp = substr_count($q, '&');
    $filterish = preg_match_all('/(^|&)(seria|kolor|rozmiar|marka|dostepnosc|kategorie|filter_|min_price|max_price)=/i', '&' . $q);
    if ($amp >= 4 || $filterish >= 3) {
        status_header(410);
        header('Content-Type: text/plain; charset=UTF-8');
        header('Cache-Control: no-store');
        echo "Gone\n";
        exit;
    }
}, 1);

/** Keep robots.txt explicit for polite crawlers. */
add_filter('robots_txt', static function ($output, $public) {
    if (!$public) {
        return $output;
    }
    $extra = implode("\n", [
        '',
        '# AI / scrapers — faceted filters must not be crawled',
        'User-agent: GPTBot',
        'Disallow: /',
        'User-agent: ChatGPT-User',
        'Disallow: /',
        'User-agent: ClaudeBot',
        'Disallow: /',
        'User-agent: anthropic-ai',
        'Disallow: /',
        'User-agent: Amazonbot',
        'Disallow: /',
        'User-agent: Bytespider',
        'Disallow: /',
        'User-agent: CCBot',
        'Disallow: /',
        'User-agent: meta-externalagent',
        'Disallow: /',
        'User-agent: FacebookBot',
        'Disallow: /',
        '',
        // No blanket Disallow: /*?* — Woo/Merchant landing pages use ?attribute_pa_*.
        // Block facet spam query params + Filter Everything path taxonomies instead.
        'User-agent: *',
        'Disallow: /*?seria=',
        'Disallow: /*?kolor=',
        'Disallow: /*?rozmiar=',
        'Disallow: /*?marka=',
        'Disallow: /*?dostepnosc=',
        'Disallow: /*?filter_',
        'Disallow: /*?min_price=',
        'Disallow: /*?max_price=',
        'Disallow: /seria/',
        'Disallow: /kolor/',
        'Disallow: /rozmiar/',
        'Disallow: /marka/',
        'Disallow: /dostepnosc/',
        '',
        'User-agent: Googlebot',
        'Allow: /*?attribute_pa_',
        'Allow: /*?*attribute_pa_',
    ]);
    return rtrim((string) $output) . "\n" . $extra . "\n";
}, 10050, 2);
