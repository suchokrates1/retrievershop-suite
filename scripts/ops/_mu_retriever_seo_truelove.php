<?php
/**
 * Plugin Name: Retriever SEO Truelove
 * Description: Force titles for szelki/smycze, category FAQ, robots allow product attrs for Googlebot (Merchant).
 */
if (!defined('ABSPATH')) {
    exit;
}

/**
 * AIOSEO sometimes falls back to "Szelki - Retriever Shop" — force money titles.
 */
add_filter('pre_get_document_title', static function ($title) {
    if (is_admin()) {
        return $title;
    }
    if (is_tax('product_cat', 'szelki')) {
        return 'Szelki Truelove dla psa — rozmiary i kolory | Retriever Shop';
    }
    if (is_tax('product_cat', 'smycze')) {
        return 'Smycze Truelove dla psa | Retriever Shop';
    }
    return $title;
}, 100);

add_filter('aioseo_title', static function ($title) {
    if (is_tax('product_cat', 'szelki')) {
        return 'Szelki Truelove dla psa — rozmiary i kolory | Retriever Shop';
    }
    if (is_tax('product_cat', 'smycze')) {
        return 'Smycze Truelove dla psa | Retriever Shop';
    }
    return $title;
}, 100);

add_filter('aioseo_description', static function ($desc) {
    if (is_tax('product_cat', 'szelki')) {
        return 'Szelki dla psa Truelove: Front Line, Premium, Security, Tropical, Lumen i inne. Dobierz kolor i rozmiar — wysyłka do 16:00 z Legnicy, InPost.';
    }
    if (is_tax('product_cat', 'smycze')) {
        return 'Smycze Truelove i akcesoria spacerowe — klasyczne, z amortyzatorem i materiałowe. Wysyłka do 16:00 z Legnicy.';
    }
    return $desc;
}, 100);

/** FAQPage JSON-LD on szelki category */
add_action('wp_head', static function () {
    if (!is_tax('product_cat', 'szelki')) {
        return;
    }
    $faq = get_option('rs_szelki_faq', []);
    if (!is_array($faq) || count($faq) < 2) {
        return;
    }
    $entities = [];
    foreach ($faq as $row) {
        $q = trim((string) ($row['q'] ?? ''));
        $a = trim((string) ($row['a'] ?? ''));
        if ($q === '' || $a === '') {
            continue;
        }
        $entities[] = [
            '@type' => 'Question',
            'name' => $q,
            'acceptedAnswer' => [
                '@type' => 'Answer',
                'text' => $a,
            ],
        ];
    }
    if (count($entities) < 2) {
        return;
    }
    echo '<script type="application/ld+json" id="rs-szelki-faq">'
        . wp_json_encode([
            '@context' => 'https://schema.org',
            '@type' => 'FAQPage',
            'mainEntity' => $entities,
        ], JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES)
        . "</script>\n";
}, 35);

/**
 * Robots: keep facet blocks, but allow Woo product attribute query strings
 * for Googlebot (Merchant landing pages use ?attribute_pa_*).
 *
 * Previous global Disallow: /*?* blocked Shopping crawls.
 */
add_filter('robots_txt', static function ($output, $public) {
    if (!$public) {
        return $output;
    }
    // Strip blanket query disallow if any earlier filter still emits it.
    $lines = preg_split("/\r\n|\n|\r/", (string) $output) ?: [];
    $out = [];
    foreach ($lines as $line) {
        $trim = trim($line);
        if (preg_match('#^Disallow:\s*/\*\?\*?\s*$#i', $trim)) {
            continue;
        }
        $out[] = $line;
    }
    return rtrim(implode("\n", $out)) . "\n";
}, 10100, 2);
