<?php
/**
 * Pack 2: free shipping cleanup, category SEO titles, guides + internal links,
 * seed Allegro trust option, purge caches.
 */
require '/var/www/html/wp-load.php';
echo 'hostname=' . gethostname() . "\n";

// 1) Free shipping method: always free (no 249 threshold)
$zones = WC_Shipping_Zones::get_zones();
foreach ($zones as $z) {
    foreach ($z['shipping_methods'] as $m) {
        if ($m->id === 'free_shipping') {
            $m->update_option('min_amount', '0');
            $m->update_option('requires', '');
            $m->update_option('title', 'Darmowa wysyłka');
            echo "free_shipping_cleared instance={$m->instance_id}\n";
        }
    }
}

// 2) Seed Allegro trust from JSON file if present
$seed = '/tmp/rs_allegro_trust.json';
if (file_exists($seed)) {
    $j = json_decode(file_get_contents($seed), true);
    if (is_array($j) && !empty($j['recommended_percentage'])) {
        update_option('rs_allegro_trust', $j, false);
        set_transient('rs_allegro_trust', $j, 6 * HOUR_IN_SECONDS);
        echo "allegro_option_seeded total={$j['ratings_received_total']}\n";
    }
}
update_option('rs_magazyn_trust_url', 'https://magazyn.retrievershop.pl/api/shop-trust/allegro', false);

// 3) Category SEO titles/descriptions (AIOSEO + term description already enriched)
$cat_seo = [
    'szelki' => [
        'title' => 'Szelki dla psa Truelove – rozmiary i kolory | Retrievershop',
        'desc' => 'Szelki guard i spacerowe Truelove. Darmowa dostawa InPost, wysyłka do 16:00 z Legnicy. Dobór rozmiaru: 782 865 895.',
    ],
    'smycze' => [
        'title' => 'Smycz dla psa Truelove – treningowe i spacerowe | Retrievershop',
        'desc' => 'Smycze Truelove w wersjach treningowych i spacerowych. Darmowa dostawa, wysyłka z Legnicy do 16:00.',
    ],
    'obroza' => [
        'title' => 'Obroża dla psa Truelove – kolory i rozmiary | Retrievershop',
        'desc' => 'Obroże Truelove dopasowane do szelek. Zmierz szyję psa i wybierz rozmiar. Darmowa dostawa InPost.',
    ],
    'pasy-bezpieczenstwa' => [
        'title' => 'Pas bezpieczeństwa dla psa do samochodu | Retrievershop',
        'desc' => 'Pasy samochodowe dla psa Truelove. Bezpieczny transport. Darmowa dostawa, wysyłka z Legnicy.',
    ],
    'saszetki' => [
        'title' => 'Saszetki i torby na smakołyki dla psa | Retrievershop',
        'desc' => 'Saszetki treningowe Truelove. Darmowa dostawa InPost z magazynu w Legnicy.',
    ],
    'pas-trekkingowy' => [
        'title' => 'Pas trekkingowy do biegania z psem | Retrievershop',
        'desc' => 'Pasy biodrowe Truelove do dogtrekkingu i biegania. Darmowa dostawa, pomoc w doborze: 782 865 895.',
    ],
    'kapok' => [
        'title' => 'Kapok / kamizelka ratunkowa dla psa | Retrievershop',
        'desc' => 'Kapoki i kamizelki dla psów. Sprawdź rozmiary. Darmowa dostawa InPost.',
    ],
    'kamizelka' => [
        'title' => 'Kamizelka dla psa – odblaski i ochrona | Retrievershop',
        'desc' => 'Kamizelki dla psów Truelove. Widoczność i komfort. Darmowa dostawa z Legnicy.',
    ],
    'amortyzator' => [
        'title' => 'Amortyzator do smyczy – komfort spaceru | Retrievershop',
        'desc' => 'Amortyzatory do smyczy Truelove. Mniej szarpnięć. Darmowa dostawa InPost.',
    ],
    'linka' => [
        'title' => 'Linka treningowa dla psa | Retrievershop',
        'desc' => 'Linki treningowe Truelove. Darmowa dostawa, wysyłka do 16:00 z Legnicy.',
    ],
];
foreach ($cat_seo as $slug => $meta) {
    $term = get_term_by('slug', $slug, 'product_cat');
    if (!$term || is_wp_error($term)) {
        echo "cat_missing {$slug}\n";
        continue;
    }
    update_term_meta($term->term_id, '_aioseo_title', $meta['title']);
    update_term_meta($term->term_id, '_aioseo_description', $meta['desc']);
    echo "cat_seo {$slug}\n";
}

// 4) Internal links on existing guides
$guides_patch = [
    'jak-dobrac-rozmiar-szelek-dla-psa' => [
        'append' => '<h2>Zobacz też</h2><ul>'
            . '<li><a href="/kategoria-produktu/szelki/">Szelki dla psa</a></li>'
            . '<li><a href="/kategoria-produktu/obroza/">Obroże</a></li>'
            . '<li><a href="/faq/">FAQ – dostawa i zwroty</a></li>'
            . '<li><a href="/produkt/szelki-dla-psa-truelove-front-line-premium/">Szelki Front Line Premium</a></li>'
            . '</ul>',
    ],
    'pas-bezpieczenstwa-dla-psa-w-samochodzie' => [
        'append' => '<h2>Zobacz też</h2><ul>'
            . '<li><a href="/kategoria-produktu/pasy-bezpieczenstwa/">Pasy bezpieczeństwa</a></li>'
            . '<li><a href="/kategoria-produktu/szelki/">Szelki do auta i spaceru</a></li>'
            . '<li><a href="/dostawa/">Darmowa dostawa InPost</a></li>'
            . '</ul>',
    ],
];
foreach ($guides_patch as $slug => $cfg) {
    $posts = get_posts(['name' => $slug, 'post_type' => 'post', 'post_status' => 'any', 'numberposts' => 1]);
    if (!$posts) {
        echo "guide_missing {$slug}\n";
        continue;
    }
    $p = $posts[0];
    if (strpos($p->post_content, 'Zobacz też') !== false) {
        echo "guide_links_ok {$slug}\n";
        continue;
    }
    wp_update_post(['ID' => $p->ID, 'post_content' => rtrim($p->post_content) . "\n\n" . $cfg['append']]);
    echo "guide_links_added {$slug}\n";
}

// 5) New long-tail guides
$new_guides = [
    [
        'slug' => 'szelki-czy-obroza-co-wybrac',
        'title' => 'Szelki czy obroża — co wybrać dla psa?',
        'content' => <<<'HTML'
<p>Wybór między szelkami a obrożą zależy od psa, stylu spacerów i komfortu. Poniżej krótkie porównanie — bez marketingowego bełkotu.</p>
<h2>Kiedy lepsze są szelki</h2>
<ul>
<li>Pies ciągnie — szelki rozkładają siłę na klatkę, nie na szyję.</li>
<li>Szczeniak lub rasa brachycefaliczna (krótki pysk).</li>
<li>Bieganie, trekking, dłuższe wypady.</li>
</ul>
<h2>Kiedy wystarczy obroża</h2>
<ul>
<li>Spokojny pies na luźnej smyczy.</li>
<li>Identyfikacja (adresówka) — obroża i tak warto mieć na co dzień.</li>
<li>Krótkie wyjścia „pod blok”.</li>
</ul>
<p>W praktyce wielu opiekunów łączy oba: <strong>obroża na co dzień + szelki na spacery</strong>.</p>
<p>Zobacz kategorię <a href="/kategoria-produktu/szelki/">szelki</a> i <a href="/kategoria-produktu/obroza/">obroże</a>. Pomoc w doborze: <a href="tel:+48782865895">782 865 895</a>.</p>
<p><em>Darmowa dostawa InPost. Zamów do 16:00 — zwykle jutro u Ciebie.</em></p>
HTML
    ],
    [
        'slug' => 'jak-wybrac-szelki-dla-duzego-psa',
        'title' => 'Jak wybrać szelki dla dużego psa?',
        'content' => <<<'HTML'
<p>Duży pies (labrador, golden, owczarek) potrzebuje szelek z solidnymi taśmami, stabilnym uchwytem i dobrze spasowanym obwodem klatki.</p>
<h2>Na co zwrócić uwagę</h2>
<ol>
<li><strong>Obwód klatki</strong> — mierz za łopatkami, nie „na oko”.</li>
<li><strong>Regulacja</strong> — minimum w kilku punktach, żeby nie ocierały pach.</li>
<li><strong>Uchwyt na grzbiecie</strong> — przydatny przy wsiadaniu do auta i na schodach.</li>
<li><strong>Punkt mocowania smyczy</strong> — klasyczny na grzbiecie; modele no-pull bywają z przodu.</li>
</ol>
<p>Poradnik rozmiarów: <a href="/jak-dobrac-rozmiar-szelek-dla-psa/">jak dobrać rozmiar szelek</a>. Katalog: <a href="/kategoria-produktu/szelki/">szelki dla psa</a>.</p>
<p>Niepewny rozmiar? Zadzwoń: <a href="tel:+48782865895">782 865 895</a>.</p>
HTML
    ],
    [
        'slug' => 'jaka-smycz-dla-psa-wybrac',
        'title' => 'Jaką smycz dla psa wybrać?',
        'content' => <<<'HTML'
<p>Smycz to nie tylko „sznurek” — długość i amortyzacja realnie wpływają na komfort spaceru.</p>
<ul>
<li><strong>Smycz klasyczna 2 m</strong> — codzienność w mieście.</li>
<li><strong>Smycz treningowa / dłuższa</strong> — praca w terenie, przywołanie.</li>
<li><strong>Amortyzator</strong> — mniej szarpnięć przy nagłych ruchach (<a href="/kategoria-produktu/amortyzator/">amortyzatory</a>).</li>
</ul>
<p>Dobierz smycz do <a href="/kategoria-produktu/szelki/">szelek</a> lub <a href="/kategoria-produktu/obroza/">obroży</a>. Cała kategoria: <a href="/kategoria-produktu/smycze/">smycze</a>.</p>
<p>Wysyłka z Legnicy, <strong>dostawa 0 zł</strong>, zamówienia do 16:00 zwykle następnego dnia.</p>
HTML
    ],
    [
        'slug' => 'jak-zmierzyc-psa-do-obrozy',
        'title' => 'Jak zmierzyć psa do obroży?',
        'content' => <<<'HTML'
<p>Zmierz obwód szyi w miejscu, gdzie ma leżeć obroża — zwykle w najszerszym punkcie u nasady szyi. Miarka krawiecka, dwa palce luzu.</p>
<ol>
<li>Pies stoi spokojnie.</li>
<li>Miarka przylega, ale nie uciska.</li>
<li>Porównaj wynik z tabelą na karcie produktu.</li>
<li>Na granicy rozmiarów — bierz większy.</li>
</ol>
<p>Obroże: <a href="/kategoria-produktu/obroza/">kategoria obroże</a>. Szelki dobierasz inaczej — patrz <a href="/jak-dobrac-rozmiar-szelek-dla-psa/">poradnik szelek</a>.</p>
<p>Pomoc: <a href="tel:+48782865895">782 865 895</a>.</p>
HTML
    ],
    [
        'slug' => 'pies-w-samochodzie-bezpieczenstwo',
        'title' => 'Pies w samochodzie — jak bezpiecznie przewozić?',
        'content' => <<<'HTML'
<p>Luźny pies w aucie to ryzyko przy hamowaniu. Najprostsze rozwiązania: transporter, kratka albo <strong>pas bezpieczeństwa</strong> przypięty do szelek.</p>
<ul>
<li>Pas mocujesz do isofix / zaczepu pasów — zgodnie z instrukcją modelu.</li>
<li>Używaj <strong>szelek</strong>, nie samej obroży (szarpnięcie idzie w szyję).</li>
<li>Nie zostawiaj psa w nagrzanym aucie.</li>
</ul>
<p>Produkty: <a href="/kategoria-produktu/pasy-bezpieczenstwa/">pasy bezpieczeństwa</a>, <a href="/pas-bezpieczenstwa-dla-psa-w-samochodzie/">szczegółowy poradnik pasa</a>, <a href="/kategoria-produktu/szelki/">szelki</a>.</p>
<p>Darmowa dostawa InPost · tel. <a href="tel:+48782865895">782 865 895</a>.</p>
HTML
    ],
];

foreach ($new_guides as $g) {
    $exists = get_posts(['name' => $g['slug'], 'post_type' => 'post', 'post_status' => 'any', 'numberposts' => 1]);
    if ($exists) {
        echo "guide_exists {$g['slug']}\n";
        continue;
    }
    $id = wp_insert_post([
        'post_title' => $g['title'],
        'post_name' => $g['slug'],
        'post_content' => $g['content'],
        'post_status' => 'publish',
        'post_type' => 'post',
        'post_author' => 1,
    ], true);
    if (is_wp_error($id)) {
        echo "guide_err {$g['slug']} " . $id->get_error_message() . "\n";
    } else {
        update_post_meta($id, '_aioseo_title', $g['title'] . ' | Retrievershop');
        echo "guide_created {$g['slug']} #{$id}\n";
    }
}

// 6) Related note on PDP via option used by theme? skip - MU enough

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
echo "DONE\n";
