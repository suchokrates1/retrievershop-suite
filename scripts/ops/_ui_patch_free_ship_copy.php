<?php
/**
 * Surface "darmowa dostawa" in PDP banner, trust row, dostawa page, FAQ MU.
 */
require '/var/www/html/wp-load.php';
echo 'hostname=' . gethostname() . "\n";

$child = get_stylesheet_directory() . '/functions.php';
$fn = file_get_contents($child);

$ship = "Zamów do 16:00 — wyślemy jeszcze dziś. <strong>Darmowa dostawa</strong> InPost (paczkomat/kurier). Paczka zwykle jutro u Ciebie (dni robocze).";
$trust = <<<'HTML'
<div class="rs-trust-row" aria-label="Dlaczego warto">
  <div><strong>Darmowa dostawa</strong>InPost paczkomat / kurier</div>
  <div><strong>Do 16:00 → jutro</strong>Wysyłka z Legnicy</div>
  <div><strong>14 dni na zwrot</strong>Bez zbędnych formalności</div>
  <div><strong>782 865 895</strong>Pomoc przy doborze rozmiaru</div>
</div>
HTML;

// Replace ship banner echo body if present
if (preg_match('/class="rs-ship-banner"[^>]*>.*?;\s*echo\s+[\'"].*?[\'"]\s*;/s', $fn)) {
    $fn = preg_replace(
        '/(class="rs-ship-banner"[^>]*>.*?;\s*)echo\s+[\'"].*?[\'"]\s*;/s',
        '$1echo \'' . addcslashes($ship, "'") . '\';',
        $fn,
        1,
        $c1
    );
    echo "ship_banner_replaced={$c1}\n";
} else {
    // looser: replace known old string
    $old = 'Zamów do 16:00 — wyślemy jeszcze dziś. Paczka zwykle jutro u Ciebie (InPost, dni robocze).';
    if (strpos($fn, $old) !== false) {
        $fn = str_replace($old, $ship, $fn);
        echo "ship_banner_str_replace=1\n";
    } else {
        echo "ship_banner_NOT_FOUND\n";
    }
}

if (preg_match('/class="rs-trust-row".*?<\/div>\s*(?=<|$)/s', $fn)) {
    // replace whole trust row div block in PHP string - careful
}
// Replace trust row by marker
if (strpos($fn, 'rs-trust-row') !== false) {
    $fn = preg_replace(
        '/<div class="rs-trust-row"[^>]*>.*?<\/div>/s',
        trim($trust),
        $fn,
        1,
        $c2
    );
    echo "trust_row_replaced={$c2}\n";
}

file_put_contents($child, $fn);
echo "child_saved\n";

// Dostawa page
$p = get_page_by_path('dostawa');
if ($p) {
    $html = <<<'HTML'
<h2>Dostawa</h2>
<p><strong>Dostawa InPost jest u nas zawsze za 0 zł</strong> — paczkomat i kurier.</p>
<p>Zamów i opłać <strong>do godz. 16:00</strong> w dzień roboczy — nadamy paczkę tego samego dnia. W większości przypadków InPost doręcza już następnego dnia roboczego („jutro u Ciebie”).</p>
<ul>
<li><strong>Paczkomaty InPost</strong> — najwygodniejsza opcja na co dzień</li>
<li><strong>Kurier InPost</strong> — dostawa pod drzwi</li>
</ul>
<p>Wysyłamy z Legnicy. Po nadaniu dostaniesz numer przesyłki.</p>
<p>Pytania o termin? Zadzwoń: <a href="tel:+48782865895">782 865 895</a> lub napisz na <a href="mailto:kontakt@retrievershop.pl">kontakt@retrievershop.pl</a>.</p>
<h2>Płatności</h2>
<p>BLIK, szybki przelew, karta — bezpiecznie przez bramkę płatności sklepu.</p>
HTML;
    wp_update_post(['ID' => $p->ID, 'post_content' => $html]);
    echo "dostawa_updated #{$p->ID}\n";
}

// Patch MU FAQ answer about payments/shipping
$mu = WPMU_PLUGIN_DIR . '/retriever-trust.php';
$src = file_get_contents($mu);
$oldA = 'Płatności: <strong>BLIK, szybki przelew, karta</strong>. Dostawa: <strong>Paczkomaty InPost i kurier InPost</strong>. Wysyłka z Legnicy.';
$newA = 'Płatności: <strong>BLIK, szybki przelew, karta</strong>. Dostawa: <strong>InPost paczkomat i kurier — zawsze 0 zł</strong>. Wysyłka z Legnicy.';
if (strpos($src, $oldA) !== false) {
    $src = str_replace($oldA, $newA, $src);
    file_put_contents($mu, $src);
    echo "mu_faq_ship_updated\n";
} elseif (strpos($src, 'zawsze 0 zł') !== false) {
    echo "mu_faq_already_ok\n";
} else {
    echo "mu_faq_string_missing\n";
}

// Also first FAQ answer already mentions shipping day - leave it

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
