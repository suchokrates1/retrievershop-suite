<?php
/**
 * Create /instrukcja-zwrotu/ + update /zwroty/ for dual return shipping methods.
 */
require '/var/www/html/wp-load.php';
echo 'hostname=' . gethostname() . "\n";

function rs_upsert_page(string $slug, string $title, string $content): int {
    $existing = get_page_by_path($slug);
    $data = [
        'post_title' => $title,
        'post_name' => $slug,
        'post_content' => $content,
        'post_status' => 'publish',
        'post_type' => 'page',
    ];
    if ($existing) {
        $data['ID'] = $existing->ID;
        $id = wp_update_post($data, true);
    } else {
        $id = wp_insert_post($data, true);
    }
    if (is_wp_error($id)) {
        fwrite(STDERR, $id->get_error_message() . "\n");
        return 0;
    }
    return (int) $id;
}

$form_url = home_url('/wniosek-o-odstapienie/');
$account_url = function_exists('wc_get_page_permalink') ? wc_get_page_permalink('myaccount') : home_url('/moje-konto/');

$instr_id = rs_upsert_page(
    'instrukcja-zwrotu',
    'Instrukcja zwrotu',
    '<div class="rs-zwroty"><p>Po złożeniu wniosku o odstąpienie wybierz sposób odesłania paczki.</p>[rs_return_instructions]</div>'
);
echo "instrukcja_zwrotu=#{$instr_id}\n";

$zwroty_html = <<<HTML
<div class="rs-zwroty">
<p><strong>Zwrot zamówienia załatwisz jednym kliknięciem</strong> — bez mailowania i szukania formularzy PDF. Zgodnie z prawem UE (odstąpienie od umowy na odległość) masz u nas elektroniczny wniosek online.</p>

<p style="margin:18px 0"><a class="button" href="{$form_url}" style="display:inline-block;background:#C45C3E;color:#fff;padding:12px 20px;border-radius:6px;text-decoration:none;font-weight:600">Złóż wniosek o odstąpienie →</a></p>

<h2>Jak to działa (krok po kroku)</h2>
<ol>
<li>Wejdź na stronę <a href="{$form_url}"><strong>Odstąpienie od umowy</strong></a> albo w <a href="{$account_url}">Moje konto</a> → swoje zamówienie i wybierz odstąpienie.</li>
<li>Wypełnij krótki formularz i wyślij wniosek.</li>
<li>Na kolejnym ekranie wybierz sposób odesłania:
  <ul>
    <li><strong>Szybki zwrot InPost</strong> — kod do Paczkomatu; opłatę pobiera InPost przy nadaniu (gdy usługa jest aktywna).</li>
    <li><strong>Zwrot własny</strong> — wysyłasz na nasz adres w Legnicy w ciągu 14 dni od zgłoszenia (instrukcja też e-mailem).</li>
  </ul>
</li>
<li>Po otrzymaniu i sprawdzeniu paczki oddamy pieniądze <strong>tą samą metodą płatności</strong>.</li>
</ol>

<h2>Termin</h2>
<p>Masz <strong>14 dni</strong> na odstąpienie od umowy przy zakupie na odległość. Produkt powinien być kompletny i nieużywany w sposób wykraczający poza sprawdzenie (jak w sklepie stacjonarnym). Na odesłanie paczki masz <strong>14 dni od zgłoszenia</strong> wniosku.</p>

<h2>Dostawa zwrotna</h2>
<p>Koszt odesłania zwykle pokrywa kupujący (chyba że towar jest wadliwy / niezgodny z umową — wtedy uzgadniamy inaczej). Przy zwrocie własnym po nadaniu warto podać numer przesyłki.</p>

<h2>Reklamacje</h2>
<p>Reklamacje jakościowe rozpatrujemy indywidualnie — jesteśmy sklepem z własnym magazynem, nie dropshippingiem. Napisz na <a href="mailto:kontakt@retrievershop.pl">kontakt@retrievershop.pl</a> albo zadzwoń <a href="tel:+48782865895">782 865 895</a>.</p>

<p>Szczegóły prawne: <a href="/regulamin/">Regulamin</a>. Formularz odstąpienia: <a href="{$form_url}">wniosek online</a>.</p>
</div>
HTML;

$zw_id = rs_upsert_page('zwroty', 'Zwroty', $zwroty_html);
echo "zwroty=#{$zw_id}\n";

wp_cache_flush();
echo "DONE\n";
