<?php
/**
 * Plugin Name: Retriever Trust & Shop UX
 * Description: H1 hygiene, trust row, FAQ, shipping promise, related products helpers.
 */
if (!defined('ABSPATH')) {
    exit;
}

/** Demote H1 inside product description / short description to H2 (keep one real H1). */
add_filter('the_content', function ($content) {
    if (!is_singular('product') || is_admin()) {
        return $content;
    }
    $content = preg_replace('/<h1(\b[^>]*)>/i', '<h2$1>', $content);
    $content = preg_replace('/<\/h1>/i', '</h2>', $content);
    return $content;
}, 12);

add_filter('woocommerce_short_description', function ($content) {
    if (!is_string($content) || $content === '') {
        return $content;
    }
    $content = preg_replace('/<h1(\b[^>]*)>/i', '<h2$1>', $content);
    $content = preg_replace('/<\/h1>/i', '</h2>', $content);
    return $content;
}, 12);

/** Hide duplicate Blocksy page title on PDP — Woo product_title remains the only H1. */
add_action('wp_head', function () {
    if (!is_product()) {
        return;
    }
    echo '<style id="rs-pdp-h1">'
        . 'body.single-product .hero-section .page-title,'
        . 'body.single-product .hero-section header.entry-header .page-title,'
        . 'body.single-product header.entry-header .page-title,'
        . 'body.single-product .hero-section h1.page-title{display:none!important;}'
        . 'body.single-product .hero-section header.entry-header{display:none!important;}'
        . '</style>';
}, 20);

/** Prefer demoting/removing Blocksy hero title on PDP when filters exist. */
add_filter('blocksy:hero:title:tag', function ($tag) {
    if (function_exists('is_product') && is_product()) {
        return 'div';
    }
    return $tag;
}, 20);

/**
 * Hard guarantee: demote Blocksy hero <h1 class="page-title"> in final HTML.
 * CSS hide is not enough for SEO crawlers.
 */
add_action('template_redirect', function () {
    if (!function_exists('is_product') || !is_product() || is_admin()) {
        return;
    }
    ob_start(function ($html) {
        if (!is_string($html) || $html === '') {
            return $html;
        }
        // Demote only the Blocksy hero page-title, keep Woo .product_title as H1.
        $html = preg_replace(
            '/<h1(\s+[^>]*\bclass="[^"]*\bpage-title\b[^"]*"[^>]*)>(.*?)<\/h1>/is',
            '<div$1>$2</div>',
            $html,
            1
        );
        return $html;
    });
}, 0);

/** FAQ shortcode for PDP / pages */
add_shortcode('rs_faq', function ($atts = []) {
    $items = [
        [
            'q' => 'Do której godziny zamówić, żeby paczka wyszła tego samego dnia?',
            'a' => 'Zamówienia opłacone <strong>do godz. 16:00</strong> w dni robocze wysyłamy tego samego dnia — <strong>kurier/paczkomat zwykle następnego dnia roboczego</strong> (InPost).',
        ],
        [
            'q' => 'Jak dobrać rozmiar szelek lub obroży?',
            'a' => 'Zmierz obwód klatki piersiowej (szelki) lub szyi (obroża) w najszerszym miejscu. Porównaj z tabelą rozmiarów na karcie produktu. Na granicy rozmiarów wybierz większy. W razie wątpliwości zadzwoń: <a href="tel:+48782865895">782 865 895</a>.',
        ],
        [
            'q' => 'Czy mogę zwrócić produkt?',
            'a' => 'Tak — masz <strong>14 dni</strong> na odstąpienie. Wniosek składasz <strong>jednym kliknięciem</strong> na stronie <a href="/wniosek-o-odstapienie/">Odstąpienie od umowy</a> (albo z Moje konto). Instrukcja odesłania: <a href="/zwroty/">Zwroty</a>.',
        ],
        [
            'q' => 'Jakie formy płatności i dostawy oferujecie?',
            'a' => 'Płatności: <strong>BLIK, szybki przelew, karta</strong>. Dostawa: <strong>InPost paczkomat i kurier — zawsze 0 zł</strong>. Wysyłka z Legnicy.',
        ],
        [
            'q' => 'Czy produkty są oryginalne Truelove?',
            'a' => 'Tak — sprzedajemy oryginalne akcesoria Truelove. Magazyn i wysyłka prowadzimy sami z Legnicy; jesteśmy dostępni telefonicznie i mailowo przy doborze rozmiaru.',
        ],
    ];
    $html = '<div class="rs-faq" itemscope itemtype="https://schema.org/FAQPage">';
    foreach ($items as $it) {
        $html .= '<details class="rs-faq__item" itemscope itemprop="mainEntity" itemtype="https://schema.org/Question">';
        $html .= '<summary itemprop="name">' . esc_html($it['q']) . '</summary>';
        $html .= '<div class="rs-faq__a" itemscope itemprop="acceptedAnswer" itemtype="https://schema.org/Answer"><div itemprop="text">' . wp_kses_post($it['a']) . '</div></div>';
        $html .= '</details>';
    }
    $html .= '</div>';
    return $html;
});

add_action('woocommerce_after_single_product_summary', function () {
    if (!is_product()) {
        return;
    }
    echo '<div class="ct-container rs-faq-wrap"><h2>Najczęstsze pytania</h2>';
    echo do_shortcode('[rs_faq]');
    echo '</div>';
}, 12);

add_action('wp_head', function () {
    if (is_admin()) {
        return;
    }
    echo '<style id="rs-trust-faq">
.rs-trust-row{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:16px 0 10px;padding:14px 16px;background:#F3F0EB;border-radius:8px;font-size:13px;color:#5A6B6B}
.rs-trust-row strong{color:#1A3333;display:block;font-size:13px;margin-bottom:2px}
.rs-ship-banner{margin:10px 0 14px;padding:10px 14px;border-left:3px solid #C45C3E;background:#fff7f3;border-radius:0 8px 8px 0;font-size:14px;color:#1A3333}
.rs-ship-banner strong{color:#C45C3E}
.rs-faq-wrap{margin:28px auto 12px;max-width:1100px;padding:0 20px}
.rs-faq-wrap h2{font-size:22px;margin:0 0 12px;color:#1A3333}
.rs-faq__item{border:1px solid #e5e1da;border-radius:8px;background:#fff;margin:0 0 8px;padding:0 14px}
.rs-faq__item summary{cursor:pointer;font-weight:600;padding:12px 0;color:#1A3333;list-style:none}
.rs-faq__item summary::-webkit-details-marker{display:none}
.rs-faq__a{padding:0 0 12px;color:#5A6B6B;font-size:14px;line-height:1.5}
.rs-related-note{font-size:13px;color:#5A6B6B;margin:0 0 10px}
.rs-footer-trust{padding:16px 0;border-top:1px solid #e5e1da;font-size:14px}
.rs-footer-trust-links{display:flex;flex-wrap:wrap;gap:10px 18px;list-style:none;margin:0;padding:0}
.rs-footer-trust-links a{color:#1A3333;text-decoration:underline}
.rs-woo-lead{margin:0 0 16px;padding:12px 14px;background:#F3F0EB;border-radius:8px;color:#1A3333;font-size:15px;line-height:1.5}
.rs-woo-lead p{margin:0}
.rs-trust-stats{margin:8px auto 28px;max-width:1100px;padding:0 20px}
.rs-trust-stats__grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px}
.rs-trust-stat{background:#F3F0EB;border-radius:12px;padding:22px 16px;text-align:center;min-height:140px;display:flex;flex-direction:column;justify-content:center}
.rs-trust-stat__value{font-size:clamp(28px,4vw,40px);line-height:1.1;font-weight:700;color:#C45C3E;margin:0 0 8px}
.rs-trust-stat__label{font-size:14px;line-height:1.35;color:#1A3333;margin:0}
.rs-trust-stats__note{margin:12px 0 0;font-size:12px;color:#5A6B6B;text-align:center}
.rs-trust-stats__note a{color:#C45C3E}
@media (max-width:900px){.rs-trust-stats__grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media (max-width:480px){.rs-trust-stats__grid{grid-template-columns:1fr}.rs-trust-stat{min-height:110px}}
.rs-sticky-contact{display:none}
@media (max-width:781px){
body{padding-bottom:64px}
.rs-sticky-contact{display:flex;position:fixed;left:0;right:0;bottom:0;z-index:9999;gap:0;background:#1A3333;box-shadow:0 -4px 16px rgba(0,0,0,.15)}
.rs-sticky-contact a{flex:1;text-align:center;padding:14px 8px;color:#fff;text-decoration:none;font-size:14px;font-weight:600}
.rs-sticky-contact a.rs-wa{background:#2F4F4F}
}
</style>';
}, 25);

/** Allegro ratings snapshot helpers (magazyn API + WP option cache). */
function rs_allegro_trust_data(): array {
    $cached = get_transient('rs_allegro_trust');
    if (
        is_array($cached)
        && !empty($cached['recommended_percentage'])
        && isset($cached['orders_rounded_100'])
    ) {
        return $cached;
    }
    $url = (string) get_option('rs_magazyn_trust_url', 'https://magazyn.retrievershop.pl/api/shop-trust/allegro');
    $resp = wp_remote_get($url, ['timeout' => 8, 'headers' => ['Accept' => 'application/json']]);
    $data = null;
    if (!is_wp_error($resp) && wp_remote_retrieve_response_code($resp) === 200) {
        $json = json_decode(wp_remote_retrieve_body($resp), true);
        if (is_array($json) && !empty($json['allegro']) && is_array($json['allegro'])) {
            $data = $json['allegro'];
        }
    }
    if (!$data) {
        $opt = get_option('rs_allegro_trust');
        if (is_array($opt)) {
            $data = $opt;
        }
    }
    if (!$data) {
        return [];
    }
    set_transient('rs_allegro_trust', $data, 6 * HOUR_IN_SECONDS);
    update_option('rs_allegro_trust', $data, false);
    return $data;
}

function rs_trust_stats_html(): string {
    $d = rs_allegro_trust_data();
    if (!$d) {
        return '';
    }
    $pct = (string) ($d['recommended_percentage'] ?? '');
    $ratings = (int) ($d['ratings_received_total'] ?? 0);
    $orders = (int) ($d['orders_rounded_100'] ?? 0);
    if ($orders < 100 && !empty($d['orders_total'])) {
        $orders = intdiv((int) $d['orders_total'], 100) * 100;
    }
    $since = (string) ($d['seller_since'] ?? '');
    $year = $since !== '' ? substr($since, 0, 4) : '2017';
    $url = esc_url((string) ($d['profile_url'] ?? 'https://allegro.pl/uzytkownik/Retriever_Shop'));
    if ($pct === '' || $ratings < 1) {
        return '';
    }
    $pct_show = esc_html(str_replace(',0', '', $pct));
    $cards = [
        ['value' => $pct_show . '%', 'label' => 'poleceń na Allegro'],
        ['value' => (string) $ratings, 'label' => 'ocen sprzedawcy Allegro'],
        ['value' => $orders >= 100 ? ($orders . '+') : (string) max($orders, 0), 'label' => 'zrealizowanych zamówień'],
        ['value' => 'od ' . esc_html($year), 'label' => 'prowadzimy sklep'],
    ];
    $html = '<div class="rs-trust-stats" aria-label="Statystyki zaufania">'
        . '<div class="rs-trust-stats__grid">';
    foreach ($cards as $card) {
        $html .= '<div class="rs-trust-stat">'
            . '<p class="rs-trust-stat__value">' . esc_html($card['value']) . '</p>'
            . '<p class="rs-trust-stat__label">' . esc_html($card['label']) . '</p>'
            . '</div>';
    }
    $html .= '</div>'
        . '<p class="rs-trust-stats__note">Oceny pochodzą ze sklepu Allegro '
        . '<a href="' . $url . '" target="_blank" rel="noopener">Retriever_Shop</a>'
        . ' — nie są to opinie produktów w tym sklepie. Liczba zamówień z magazynu, zaokrąglona w dół do 100.</p>'
        . '</div>';
    return $html;
}

/** Backward-compatible shortcode alias. */
function rs_allegro_badge_html(): string {
    return rs_trust_stats_html();
}

add_shortcode('rs_allegro_trust', function () {
    return rs_trust_stats_html();
});
add_shortcode('rs_trust_stats', function () {
    return rs_trust_stats_html();
});

/** Insert big trust stats above "Opinie klientów" in homepage Elementor section. */
add_action('elementor/frontend/widget/before_render', function ($widget) {
    if (!is_front_page() || !is_object($widget) || !method_exists($widget, 'get_name')) {
        return;
    }
    if ($widget->get_name() !== 'heading') {
        return;
    }
    $title = (string) ($widget->get_settings_for_display('title') ?? '');
    if (stripos($title, 'Opinie klientów') === false) {
        return;
    }
    static $done = false;
    if ($done) {
        return;
    }
    $done = true;
    echo rs_trust_stats_html();
}, 5);

/** Sticky phone / WhatsApp on mobile */
add_action('wp_footer', function () {
    if (is_admin()) {
        return;
    }
    echo '<div class="rs-sticky-contact" aria-label="Kontakt">'
        . '<a href="tel:+48782865895">Zadzwoń</a>'
        . '<a class="rs-wa" href="https://wa.me/48782865895" target="_blank" rel="noopener">WhatsApp</a>'
        . '</div>';
}, 40);

/** Homepage FAQ after page content (Elementor). */
add_filter('the_content', function ($content) {
    if (!is_front_page() || !in_the_loop() || !is_main_query() || is_admin()) {
        return $content;
    }
    if (strpos($content, 'rs-faq') !== false) {
        return $content;
    }
    $faq = '<div class="rs-faq-wrap"><h2>Najczęstsze pytania</h2>'
        . do_shortcode('[rs_faq]')
        . '<p style="font-size:14px;color:#5A6B6B">Więcej: <a href="/faq/">FAQ</a> · <a href="/dostawa/">Dostawa</a> · <a href="/zwroty/">Zwroty</a></p></div>';
    return $content . $faq;
}, 30);

/** Footer trust links strip. */
add_action('wp_footer', function () {
    $html = get_option('rs_footer_trust_html');
    if (!$html || is_admin()) {
        return;
    }
    echo '<div class="ct-container rs-footer-trust"><nav aria-label="Informacje sklepu">' . $html . '</nav></div>';
}, 5);

/** Page hero title clearance under sticky header */
add_action('wp_head', function () {
    if (is_admin() || is_front_page() || is_singular('product')) {
        return;
    }
    if (!is_page() && !is_singular('post')) {
        return;
    }
    echo '<style id="rs-page-hero-pad">'
        . 'body.page .hero-section[data-type="type-2"],'
        . 'body.single-post .hero-section[data-type="type-2"]{'
        . 'padding-top:clamp(96px,12vw,140px)!important;'
        . 'padding-bottom:28px!important;'
        . 'min-height:0!important;'
        . '}'
        . 'body.page .hero-section .page-title,'
        . 'body.single-post .hero-section .page-title{'
        . 'margin-top:0;'
        . '}'
        . '</style>';
}, 30);
