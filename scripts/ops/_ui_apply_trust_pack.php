<?php
/**
 * One-shot: trust pack — pages, cats, footer, trust row, content H1 demote, guides.
 */
require '/var/www/html/wp-load.php';
wp_set_current_user(1);

function rs_log($m) { echo $m . "\n"; }

function rs_upsert_page(string $slug, string $title, string $content, string $status = 'publish'): int {
    $existing = get_page_by_path($slug);
    $data = [
        'post_title' => $title,
        'post_name' => $slug,
        'post_content' => $content,
        'post_status' => $status,
        'post_type' => 'page',
    ];
    if ($existing) {
        $data['ID'] = $existing->ID;
        $id = wp_update_post($data, true);
    } else {
        $id = wp_insert_post($data, true);
    }
    if (is_wp_error($id)) {
        rs_log("PAGE ERR $slug " . $id->get_error_message());
        return 0;
    }
    rs_log("page $slug #$id");
    return (int) $id;
}

// ---------- 1) MU trust plugin ----------
$mu_candidates = [
    '/tmp/_mu_retriever_trust.php',
    ABSPATH . '../_mu_retriever_trust.php',
];
$mu_src = '';
foreach ($mu_candidates as $cand) {
    if (is_readable($cand)) {
        $mu_src = file_get_contents($cand);
        break;
    }
}
if ($mu_src === '') {
    fwrite(STDERR, "MU source missing\n");
    exit(1);
}
file_put_contents(ABSPATH . 'wp-content/mu-plugins/retriever-trust.php', $mu_src);
rs_log('mu_trust_deployed');

// ---------- 2) Child theme: trust row + ship banner ----------
$child = ABSPATH . 'wp-content/themes/blocksy-child/functions.php';
$child_src = file_get_contents($child);

// Replace trust row block if present
$trust_new = <<<'PHP'
/**
 * Retriever Shop UI — PDP trust + size guide + archive price
 */
add_action('woocommerce_single_product_summary', function () {
    echo '<div class="rs-ship-banner">';
    echo '<strong>Zamów do 16:00</strong> — wyślemy jeszcze dziś. Paczka zwykle <strong>jutro u Ciebie</strong> (InPost, dni robocze).';
    echo '</div>';
    echo '<div class="rs-trust-row">';
    echo '<div><strong>Wysyłka z Legnicy</strong>InPost paczkomat / kurier</div>';
    echo '<div><strong>Zwroty</strong>14 dni na odstąpienie</div>';
    echo '<div><strong>Kontakt</strong><a href="tel:+48782865895">782 865 895</a></div>';
    echo '<div><strong>Płatności</strong>BLIK, przelew, karta</div>';
    echo '</div>';
}, 35);
PHP;

if (preg_match('/\/\*\*\s*\n \* Retriever Shop UI[\s\S]*?add_action\(\'woocommerce_single_product_summary\'[\s\S]*?\}, 35\);/', $child_src)) {
    $child_src = preg_replace(
        '/\/\*\*\s*\n \* Retriever Shop UI[\s\S]*?add_action\(\'woocommerce_single_product_summary\'[\s\S]*?\}, 35\);/',
        trim($trust_new),
        $child_src,
        1
    );
    rs_log('child_trust_replaced');
} elseif (strpos($child_src, 'rs-ship-banner') === false) {
    // replace simpler pattern
    $child_src = preg_replace(
        '/add_action\(\'woocommerce_single_product_summary\', function \(\) \{[\s\S]*?\}, 35\);/',
        trim($trust_new),
        $child_src,
        1
    );
    rs_log('child_trust_regex2');
}

// Checkout trust
if (strpos($child_src, 'woocommerce_proceed_to_checkout') !== false) {
    $child_src = preg_replace(
        '/add_action\(\'woocommerce_proceed_to_checkout\'[\s\S]*?\}, 20\);/',
        "add_action('woocommerce_proceed_to_checkout', function () {\n"
        . "    echo '<div class=\"rs-trust-row\" style=\"margin-top:12px\">';\n"
        . "    echo '<div><strong>Bezpieczne płatności</strong>BLIK / karta / przelew</div>';\n"
        . "    echo '<div><strong>InPost</strong>Paczkomaty i kurier</div>';\n"
        . "    echo '<div><strong>Wysyłka do 16:00</strong>Zwykle jutro u Ciebie</div>';\n"
        . "    echo '<div><strong>Pytania?</strong><a href=\"tel:+48782865895\">782 865 895</a></div>';\n"
        . "    echo '</div>';\n"
        . "}, 20);",
        $child_src,
        1
    );
}

// Related products note
if (strpos($child_src, 'rs-related-note') === false) {
    $child_src .= "\n\nadd_action('woocommerce_before_template_part', function (\$slug) {\n"
        . "    if (\$slug === 'single-product/related.php') {\n"
        . "        echo '<p class=\"rs-related-note\">Dobierz komplet: szelki + smycz + obroża z tej samej kolekcji wyglądają spójnie i wygodniej się spina.</p>';\n"
        . "    }\n"
        . "}, 10, 1);\n";
}

file_put_contents($child, $child_src);
rs_log('child_functions_saved');

// ---------- 3) Pages ----------
$dostawa = <<<'HTML'
<h2>Dostawa</h2>
<p><strong>Zamów i opłać do godz. 16:00</strong> w dzień roboczy — nadamy paczkę <strong>tego samego dnia</strong>. W większości przypadków InPost doręcza <strong>już następnego dnia roboczego</strong> („jutro u Ciebie”).</p>
<ul>
<li><strong>Paczkomaty InPost</strong> — najwygodniejsza opcja na co dzień</li>
<li><strong>Kurier InPost</strong> — dostawa pod drzwi</li>
</ul>
<p>Wysyłamy z Legnicy. Po nadaniu dostaniesz numer przesyłki.</p>
<p>Pytania o termin? Zadzwoń: <a href="tel:+48782865895">782 865 895</a> lub napisz na <a href="mailto:kontakt@retrievershop.pl">kontakt@retrievershop.pl</a>.</p>
<h3>Płatności</h3>
<p>BLIK, szybki przelew, karta — bezpiecznie przez bramkę płatności sklepu.</p>
HTML;

$zwroty = <<<'HTML'
<h2>Zwroty i reklamacje</h2>
<p>Przy zakupie na odległość masz <strong>14 dni</strong> na odstąpienie od umowy (produkt kompletny, nieużywany w sposób wykraczający poza sprawdzenie).</p>
<ol>
<li>Napisz na <a href="mailto:kontakt@retrievershop.pl">kontakt@retrievershop.pl</a> lub zadzwoń <a href="tel:+48782865895">782 865 895</a>.</li>
<li>Wyślij produkt z numerem zamówienia na adres, który podamy w odpowiedzi.</li>
<li>Po otrzymaniu zwrotu oddamy środki tą samą metodą płatności.</li>
</ol>
<p>Reklamacje jakościowe rozpatrujemy indywidualnie — jesteśmy sklepem z magazynem w Legnicy, nie anonimowym dropshippingiem.</p>
<p>Szczegóły prawne: zobacz też <a href="/regulamin/">Regulamin</a>.</p>
HTML;

$regulamin = <<<'HTML'
<h2>Regulamin sklepu Retriever Shop</h2>
<p>Niniejszy regulamin określa zasady zakupów w sklepie internetowym Retriever Shop (retrievershop.pl).</p>
<h3>§1 Sprzedawca</h3>
<p>Sprzedawcą jest podmiot prowadzący sklep Retriever Shop. Kontakt: <a href="mailto:kontakt@retrievershop.pl">kontakt@retrievershop.pl</a>, tel. <a href="tel:+48782865895">782 865 895</a>. Magazyn i wysyłka: Legnica.</p>
<h3>§2 Zamówienia</h3>
<p>Zamówienia składa się przez koszyk sklepu. Umowa sprzedaży zawierana jest z chwilą potwierdzenia przyjęcia zamówienia. Zamówienia opłacone do 16:00 w dni robocze realizujemy tego samego dnia.</p>
<h3>§3 Ceny i płatności</h3>
<p>Ceny podane są w PLN i zawierają VAT (jeśli dotyczy). Akceptujemy BLIK, przelew i kartę.</p>
<h3>§4 Dostawa</h3>
<p>Dostawa przez InPost (paczkomat / kurier). Koszty dostawy widoczne są w koszyku przed płatnością.</p>
<h3>§5 Odstąpienie i reklamacje</h3>
<p>Konsument może odstąpić od umowy w ciągu 14 dni — szczegóły na stronie <a href="/zwroty/">Zwroty</a>.</p>
<h3>§6 Dane osobowe</h3>
<p>Zasady przetwarzania danych: <a href="/polityka-prywatnosci/">Polityka prywatności</a>.</p>
HTML;

$privacy = <<<'HTML'
<h2>Polityka prywatności</h2>
<p>Dbamy o Twoje dane. Administratorem danych podawanych w sklepie i formularzach jest Retriever Shop. Kontakt: <a href="mailto:kontakt@retrievershop.pl">kontakt@retrievershop.pl</a>, tel. <a href="tel:+48782865895">782 865 895</a>.</p>
<h3>Jakie dane zbieramy</h3>
<ul>
<li>dane zamówienia (imię, adres, e-mail, telefon, treść zamówienia),</li>
<li>dane konta (jeśli zakładane),</li>
<li>dane newslettera (e-mail) — tylko za zgodą,</li>
<li>dane techniczne (cookies, analityka — np. Umami) w zakresie niezbędnym do działania sklepu.</li>
</ul>
<h3>Cel i podstawa</h3>
<p>Realizacja umowy sprzedaży, obsługa zwrotów, obowiązki księgowe, marketing za zgodą (newsletter), bezpieczeństwo serwisu.</p>
<h3>Odbiorcy</h3>
<p>Dostawcy płatności, firmy kurierskie (InPost), hosting / infrastruktura sklepu — wyłącznie w zakresie potrzebnym do realizacji usług.</p>
<h3>Twoje prawa</h3>
<p>Masz prawo dostępu, sprostowania, usunięcia, ograniczenia, sprzeciwu i przenoszenia danych oraz skargi do UODO. Newsletter możesz wypisać w każdej chwili.</p>
HTML;

$faq_page = <<<'HTML'
<h2>Najczęstsze pytania</h2>
<p>Krótko i konkretnie — dostawa, rozmiary, zwroty i płatności.</p>
[rs_faq]
<p>Nie znalazłeś odpowiedzi? Zadzwoń <a href="tel:+48782865895">782 865 895</a> lub napisz na <a href="mailto:kontakt@retrievershop.pl">kontakt@retrievershop.pl</a>.</p>
HTML;

$id_dostawa = rs_upsert_page('dostawa', 'Dostawa i płatności', $dostawa);
$id_zwroty = rs_upsert_page('zwroty', 'Zwroty', $zwroty);
$id_regulamin = rs_upsert_page('regulamin', 'Regulamin', $regulamin);
$id_privacy = rs_upsert_page('polityka-prywatnosci', 'Polityka prywatności', $privacy);
$id_faq = rs_upsert_page('faq', 'FAQ — pytania i odpowiedzi', $faq_page);

// Enrich O nas slightly if short on trust signals
$onas = get_page_by_path('o-nas');
if ($onas && stripos($onas->post_content, '782 865 895') === false) {
    $extra = '<p><strong>Retriever Shop</strong> — sklep z akcesoriami spacerowymi dla psów. Magazyn i wysyłka z Legnicy. Zamówienia do 16:00 wysyłamy tego samego dnia. Tel. <a href="tel:+48782865895">782 865 895</a>, <a href="mailto:kontakt@retrievershop.pl">kontakt@retrievershop.pl</a>.</p>';
    wp_update_post([
        'ID' => $onas->ID,
        'post_content' => $extra . "\n" . $onas->post_content,
    ]);
    rs_log('o-nas_enriched');
}

// ---------- 4) Footer menu ----------
$menu_name = 'Stopka — zaufanie';
$menu = wp_get_nav_menu_object($menu_name);
if (!$menu) {
    $menu_id = wp_create_nav_menu($menu_name);
} else {
    $menu_id = (int) $menu->term_id;
}
// clear items
$items = wp_get_nav_menu_items($menu_id);
if ($items) {
    foreach ($items as $it) {
        wp_delete_post($it->ID, true);
    }
}
$footer_links = [
    ['title' => 'Dostawa', 'object_id' => $id_dostawa],
    ['title' => 'Zwroty', 'object_id' => $id_zwroty],
    ['title' => 'FAQ', 'object_id' => $id_faq],
    ['title' => 'Regulamin', 'object_id' => $id_regulamin],
    ['title' => 'Polityka prywatności', 'object_id' => $id_privacy],
    ['title' => 'O nas', 'object_id' => ($onas ? (int) $onas->ID : 0)],
    ['title' => 'Kontakt', 'object_id' => (($k = get_page_by_path('kontakt')) ? (int) $k->ID : 0)],
];
$pos = 1;
foreach ($footer_links as $link) {
    if (empty($link['object_id'])) {
        continue;
    }
    wp_update_nav_menu_item($menu_id, 0, [
        'menu-item-title' => $link['title'],
        'menu-item-object' => 'page',
        'menu-item-object-id' => $link['object_id'],
        'menu-item-type' => 'post_type',
        'menu-item-status' => 'publish',
        'menu-item-position' => $pos++,
    ]);
}
$locs = get_theme_mod('nav_menu_locations', []);
if (!is_array($locs)) {
    $locs = [];
}
$locs['footer'] = $menu_id;
// Blocksy sometimes uses footer-menu / menu_3
$locs['footer_menu'] = $menu_id;
$locs['menu_2'] = $menu_id;
set_theme_mod('nav_menu_locations', $locs);
rs_log("footer_menu #$menu_id assigned");

// Also add text widget link list to footer sidebar if empty-ish
$sidebars = wp_get_sidebars_widgets();
$html_links = '<ul class="rs-footer-trust-links">'
    . '<li><a href="/dostawa/">Dostawa (do 16:00 → jutro)</a></li>'
    . '<li><a href="/zwroty/">Zwroty 14 dni</a></li>'
    . '<li><a href="/faq/">FAQ</a></li>'
    . '<li><a href="/regulamin/">Regulamin</a></li>'
    . '<li><a href="/polityka-prywatnosci/">Polityka prywatności</a></li>'
    . '<li><a href="tel:+48782865895">782 865 895</a></li>'
    . '</ul>';

// store as option for block widget injection via custom HTML in sidebar 6
$sidebars['ct-footer-sidebar-6'] = ['rs_trust_footer_html'];
// Use a custom approach: save to option and render via MU... simpler: create a Custom HTML widget
update_option('rs_footer_trust_html', $html_links);
rs_log('footer_html_option_set');

// ---------- 5) Category descriptions ----------
$cat_copy = [
    'szelki' => '<p><strong>Szelki dla psa Truelove</strong> — wygodne uprzęże guard i no-pull na codzienne spacery, bieganie i dogtrekking. Wybierz kolor i rozmiar; zamówione do 16:00 wysyłamy tego samego dnia z Legnicy.</p>',
    'smycze' => '<p><strong>Smycze dla psa</strong> Truelove (klasyczne, przepinane, automatyczne). Dobierz długość i kolor do szelek lub obroży z tej samej kolekcji.</p>',
    'obroza' => '<p><strong>Obroże dla psa</strong> materiałowe i treningowe Truelove — odblaski, wygodne zapięcia, kolory pasujące do smyczy i szelek Lumen / Active.</p>',
    'pasy-bezpieczenstwa' => '<p><strong>Pasy bezpieczeństwa dla psa do samochodu</strong> Truelove — stabilne przypięcie w aucie. Ważny element bezpiecznej podróży z psem.</p>',
    'saszetki' => '<p><strong>Saszetki na przysmaki</strong> i torebki treningowe Truelove — pod ręką na spacerze i na treningu.</p>',
    'pas-trekkingowy' => '<p><strong>Pasy trekkingowe / do biegania z psem</strong> Truelove Trek Go — wolne ręce na dogtrekking i jogging.</p>',
    'kapok' => '<p><strong>Kapoki i kamizelki ratunkowe dla psa</strong> Truelove Dive — bezpieczeństwo nad wodą i podczas wodnych aktywności.</p>',
    'kamizelka' => '<p><strong>Kamizelki chłodzące dla psa</strong> Truelove — ulga w upały na spacerze i w podróży.</p>',
    'amortyzator' => '<p><strong>Amortyzatory do smyczy</strong> Truelove — łagodzą szarpnięcia przy bieganiu i intensywnym tempie.</p>',
    'linka' => '<p><strong>Linki dla psa Hexa</strong> — solidne linki treningowe i spacerowe.</p>',
];
foreach ($cat_copy as $slug => $html) {
    $term = get_term_by('slug', $slug, 'product_cat');
    if (!$term || is_wp_error($term)) {
        continue;
    }
    wp_update_term($term->term_id, 'product_cat', ['description' => $html]);
    rs_log("cat_desc {$slug}");
}

// ---------- 6) Demote H1 in product descriptions in DB ----------
global $wpdb;
$ids = $wpdb->get_col("SELECT ID FROM {$wpdb->posts} WHERE post_type='product' AND post_status='publish' AND post_content LIKE '%<h1%'");
$n = 0;
foreach ($ids as $pid) {
    $post = get_post($pid);
    $new = preg_replace('/<h1(\b[^>]*)>/i', '<h2$1>', $post->post_content);
    $new = preg_replace('/<\/h1>/i', '</h2>', $new);
    if ($new !== $post->post_content) {
        $wpdb->update($wpdb->posts, ['post_content' => $new], ['ID' => $pid]);
        clean_post_cache($pid);
        $n++;
    }
}
rs_log("demoted_h1_in_products=$n");

// ---------- 7) Woo settings: reviews, related ----------
update_option('woocommerce_enable_reviews', 'yes');
update_option('woocommerce_review_rating_verification_required', 'no');
update_option('woocommerce_review_rating_required', 'yes');
update_option('woocommerce_enable_review_rating', 'yes');
set_theme_mod('has_product_single_title', 'no'); // reduce Blocksy duplicate title
rs_log('woo_review_and_title_settings');

// ---------- 8) Two guide posts ----------
$guides = [
    [
        'slug' => 'jak-dobrac-rozmiar-szelek-dla-psa',
        'title' => 'Jak dobrać rozmiar szelek dla psa?',
        'content' => '<p>Dobór rozmiaru szelek to najczęstsze pytanie przed zakupem. Zrób to w 3 krokach.</p>
<h2>1. Zmierz klatkę piersiową</h2>
<p>Miarka krawiecka w najszerszym miejscu klatki — zwykle kilka centymetrów za łapkami przednimi. Pies powinien stać swobodnie.</p>
<h2>2. Porównaj z tabelą na karcie produktu</h2>
<p>Każdy model Truelove (Front Line, Lumen, Adventure…) ma własne zakresy. Jeśli pies jest na granicy — bierz większy rozmiar.</p>
<h2>3. Sprawdź regulację</h2>
<p>Dobre szelki regulujesz w kilku punktach. Po założeniu między szelkami a ciałem powinny zmieścić się dwa palce.</p>
<p>Potrzebujesz pomocy? Zadzwoń <a href="tel:+48782865895">782 865 895</a> — pomożemy dobrać rozmiar. Zobacz też <a href="/produkty/?kategorie=szelki">szelki w sklepie</a> i <a href="/faq/">FAQ</a>.</p>
<p><em>Zamów do 16:00 — wyślemy dziś, paczka zwykle jutro u Ciebie.</em></p>',
    ],
    [
        'slug' => 'pas-bezpieczenstwa-dla-psa-w-samochodzie',
        'title' => 'Pas bezpieczeństwa dla psa w samochodzie — dlaczego warto',
        'content' => '<p>Luźny pies w aucie to ryzyko przy hamowaniu. Pas samochodowy dla psa to prosty sposób, by podróżować spokojniej.</p>
<h2>Do czego służy pas dla psa?</h2>
<p>Przypina szelki (lub obrożę — lepiej szelki) do gniazda pasów w aucie i ogranicza przemieszczanie się pupila.</p>
<h2>Jak używać?</h2>
<ul>
<li>najpierw dobrze dobrane <a href="/produkty/?kategorie=szelki">szelki</a>,</li>
<li>potem <a href="/produkty/?kategorie=pasy-bezpieczenstwa">pas bezpieczeństwa</a> do ISOFIX / klamry pasów,</li>
<li>krótka regulacja — pies może usiąść, ale nie skacze po kabinie.</li>
</ul>
<p>Pytania? <a href="tel:+48782865895">782 865 895</a>. Wysyłka z Legnicy — zamówienia do 16:00 zwykle następnego dnia u Ciebie.</p>',
    ],
];

foreach ($guides as $g) {
    $existing = get_page_by_path($g['slug'], OBJECT, 'post');
    if ($existing) {
        wp_update_post([
            'ID' => $existing->ID,
            'post_title' => $g['title'],
            'post_content' => $g['content'],
            'post_status' => 'publish',
        ]);
        rs_log("guide_updated {$g['slug']} #{$existing->ID}");
    } else {
        $id = wp_insert_post([
            'post_type' => 'post',
            'post_name' => $g['slug'],
            'post_title' => $g['title'],
            'post_content' => $g['content'],
            'post_status' => 'publish',
            'post_author' => 1,
        ], true);
        rs_log(is_wp_error($id) ? 'guide_err ' . $id->get_error_message() : "guide_created {$g['slug']} #$id");
    }
}

// ---------- 9) ALT backfill empty featured images ----------
$q = new WP_Query([
    'post_type' => 'product',
    'posts_per_page' => 80,
    'post_status' => 'publish',
    'fields' => 'ids',
]);
$alt_n = 0;
foreach ($q->posts as $pid) {
    $img = get_post_thumbnail_id($pid);
    if (!$img) {
        continue;
    }
    $alt = get_post_meta($img, '_wp_attachment_image_alt', true);
    if ($alt) {
        continue;
    }
    $name = get_the_title($pid);
    update_post_meta($img, '_wp_attachment_image_alt', $name);
    $alt_n++;
}
rs_log("alt_backfill=$alt_n");

wp_cache_flush();
$root = WP_CONTENT_DIR . '/cache';
if (is_dir($root)) {
    $it = new RecursiveIteratorIterator(
        new RecursiveDirectoryIterator($root, FilesystemIterator::SKIP_DOTS),
        RecursiveIteratorIterator::CHILD_FIRST
    );
    foreach ($it as $f) {
        $f->isDir() ? @rmdir($f->getPathname()) : @unlink($f->getPathname());
    }
}
$el = WP_CONTENT_DIR . '/uploads/elementor/css';
if (is_dir($el)) {
    foreach (glob($el . '/*') as $f) {
        @unlink($f);
    }
}
rs_log('DONE');
