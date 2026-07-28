<?php
/**
 * Plugin Name: Retriever FAQ Schema
 * Description: Emit FAQPage JSON-LD from H2 FAQ + H3/P pairs on how-to posts.
 */
if (!defined('ABSPATH')) {
    exit;
}

add_action('wp_head', static function () {
    if (!is_singular('post')) {
        return;
    }
    $post = get_post();
    if (!$post) {
        return;
    }
    $html = (string) $post->post_content;
    if ($html === '' || stripos($html, '<h2>FAQ</h2>') === false && stripos($html, '>FAQ</h2>') === false) {
        return;
    }

    // Slice from FAQ heading to end (or next major stop)
    if (!preg_match('/<h2[^>]*>\s*FAQ\s*<\/h2>(.*)$/is', $html, $m)) {
        return;
    }
    $faqHtml = $m[1];
    if (!preg_match_all('/<h3[^>]*>(.*?)<\/h3>\s*<p>(.*?)<\/p>/is', $faqHtml, $pairs, PREG_SET_ORDER)) {
        return;
    }
    $entities = [];
    foreach ($pairs as $pair) {
        $q = trim(wp_strip_all_tags(html_entity_decode($pair[1], ENT_QUOTES | ENT_HTML5, 'UTF-8')));
        $a = trim(wp_strip_all_tags(html_entity_decode($pair[2], ENT_QUOTES | ENT_HTML5, 'UTF-8')));
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
    $schema = [
        '@context' => 'https://schema.org',
        '@type' => 'FAQPage',
        'mainEntity' => $entities,
    ];
    echo '<script type="application/ld+json" id="rs-faq-schema">'
        . wp_json_encode($schema, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES)
        . "</script>\n";
}, 30);
