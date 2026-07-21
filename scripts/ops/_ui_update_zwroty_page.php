<?php
/**
 * Update /zwroty/ to describe one-click EU withdrawal (WebToffee).
 */
require '/var/www/html/wp-load.php';
echo 'hostname=' . gethostname() . "\n";

$form_url = home_url('/wniosek-o-odstapienie/');
$account_url = wc_get_page_permalink('myaccount');

$html = <<<HTML
<div class="rs-zwroty">
<p><strong>Zwrot zamówienia załatwisz jednym kliknięciem</strong> — bez mailowania i szukania formularzy PDF. Zgodnie z prawem UE (odstąpienie od umowy na odległość) masz u nas elektroniczny wniosek online.</p>

<p style="margin:18px 0"><a class="button" href="{$form_url}" style="display:inline-block;background:#C45C3E;color:#fff;padding:12px 20px;border-radius:6px;text-decoration:none;font-weight:600">Złóż wniosek o odstąpienie →</a></p>

<h2>Jak to działa (krok po kroku)</h2>
<ol>
<li>Wejdź na stronę <a href="{$form_url}"><strong>Odstąpienie od umowy</strong></a> albo w <a href="{$account_url}">Moje konto</a> → swoje zamówienie i wybierz odstąpienie.</li>
<li>Wypełnij krótki formularz (numer zamówienia / e-mail) i wyślij wniosek <strong>jednym kliknięciem</strong>.</li>
<li>Dostaniesz potwierdzenie i instrukcję odesłania paczki (adres zwrotu z Legnicy).</li>
<li>Po otrzymaniu i sprawdzeniu paczki oddamy pieniądze <strong>tą samą metodą płatności</strong>.</li>
</ol>

<h2>Termin</h2>
<p>Masz <strong>14 dni</strong> na odstąpienie od umowy przy zakupie na odległość. Produkt powinien być kompletny i nieużywany w sposób wykraczający poza sprawdzenie (jak w sklepie stacjonarnym).</p>

<h2>Dostawa zwrotna</h2>
<p>Koszt odesłania zwykle pokrywa kupujący (chyba że towar jest wadliwy / niezgodny z umową — wtedy uzgadniamy inaczej). Wysyłamy i przyjmujemy zwroty w Legnicy; po nadaniu warto podać numer przesyłki.</p>

<h2>Reklamacje</h2>
<p>Reklamacje jakościowe rozpatrujemy indywidualnie — jesteśmy sklepem z własnym magazynem, nie dropshippingiem. Napisz na <a href="mailto:kontakt@retrievershop.pl">kontakt@retrievershop.pl</a> albo zadzwoń <a href="tel:+48782865895">782 865 895</a>.</p>

<p>Szczegóły prawne: <a href="/regulamin/">Regulamin</a>. Formularz odstąpienia: <a href="{$form_url}">wniosek online</a>.</p>
</div>
HTML;

$p = get_page_by_path('zwroty');
if (!$p) {
    fwrite(STDERR, "zwroty page missing\n");
    exit(1);
}
wp_update_post([
    'ID' => $p->ID,
    'post_title' => 'Zwroty',
    'post_content' => $html,
]);
update_post_meta($p->ID, '_aioseo_title', 'Zwroty i odstąpienie od umowy 1 kliknięciem | Retrievershop');
update_post_meta($p->ID, '_aioseo_description', 'Zwrot zamówienia jednym kliknięciem — elektroniczny wniosek o odstąpienie od umowy (14 dni). Instrukcja, reklamacje, kontakt: 782 865 895.');
echo "zwroty_updated #{$p->ID}\n";
echo "form_url={$form_url}\n";

// FAQ answer in MU
$mu = WPMU_PLUGIN_DIR . '/retriever-trust.php';
if (file_exists($mu)) {
    $src = file_get_contents($mu);
    $old = 'Tak — masz <strong>14 dni</strong> na odstąpienie od umowy przy zakupie na odległość (produkt nieużywany, w stanie pozwalającym na odsprzedaż). Szczegóły na stronie <a href="/zwroty/">Zwroty</a>.';
    $new = 'Tak — masz <strong>14 dni</strong> na odstąpienie. Wniosek składasz <strong>jednym kliknięciem</strong> na stronie <a href="/wniosek-o-odstapienie/">Odstąpienie od umowy</a> (albo z Moje konto). Instrukcja odesłania: <a href="/zwroty/">Zwroty</a>.';
    if (strpos($src, $old) !== false) {
        file_put_contents($mu, str_replace($old, $new, $src));
        echo "mu_faq_updated\n";
    } elseif (strpos($src, 'jednym kliknięciem') !== false) {
        echo "mu_faq_already\n";
    } else {
        echo "mu_faq_string_missing\n";
    }
}

// Footer link label tweak if present
$footer = get_option('rs_footer_trust_html');
if (is_string($footer) && strpos($footer, '/zwroty/') !== false && strpos($footer, '1 klik') === false) {
    $footer2 = preg_replace('/(>Zwroty<\/a>)/', '>Zwroty (1 klik)</a>', $footer, 1);
    if ($footer2 && $footer2 !== $footer) {
        update_option('rs_footer_trust_html', $footer2, false);
        echo "footer_label_updated\n";
    }
}

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
