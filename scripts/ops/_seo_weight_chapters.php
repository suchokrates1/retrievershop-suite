<?php
require '/var/www/html/wp-load.php';
kses_remove_filters();

$tlh5651 = '<p id="rs-mfr-cm"><b>Tabela producenta (TLH5651).</b> Producent nie podaje kilogramów. Zalecany obwód klatki: XS 28–38 cm, S 38–51 cm, M 51–64 cm, L 64–76 cm, XL 76–102 cm. Regulacja taśmy jest szersza: 33–43, 43–56, 56–69, 69–81 i 81–107 cm. Przy górze zakresu bierz większy rozmiar. Rozmiaru 2XL nie ma.</p>';
$tlh5657 = '<p id="rs-mfr-cm"><b>Tabela modelu Cordura (TLH5657).</b> Producent nie podaje kilogramów. Obwód klatki: XS 33–42 cm, S 40–56 cm, M 52–65 cm, L 64–80 cm, XL 78–96 cm. Przy górze zakresu bierz większy rozmiar.</p>';

function rs_swap_kg_list(string $html, string $replacement): string
{
    if (str_contains($html, 'id="rs-mfr-cm"')) {
        return $html;
    }
    $start = null;
    foreach (['Z doświadczenia', 'TABELA ROZMIARÓW'] as $needle) {
        $pos = stripos($html, $needle);
        if ($pos !== false && ($start === null || $pos < $start)) {
            $start = $pos;
        }
    }
    if ($start === null) {
        return $html;
    }
    $tag = strrpos(substr($html, 0, $start), '<');
    if ($tag === false) {
        $tag = $start;
    }
    $kg = null;
    foreach (['38 kg', '28 kg'] as $mark) {
        $pos = stripos($html, $mark, $start);
        if ($pos !== false && ($kg === null || $pos < $kg)) {
            $kg = $pos;
        }
    }
    if ($kg === null) {
        return $html;
    }
    $end = null;
    foreach (['</ul>', '</p>'] as $close) {
        $pos = stripos($html, $close, $kg);
        if ($pos !== false && ($pos - $kg) < 500 && ($end === null || $pos < $end)) {
            $end = $pos + strlen($close);
        }
    }
    if ($end === null || $end <= $tag) {
        return $html;
    }
    return substr($html, 0, $tag) . $replacement . substr($html, $end);
}

$ids = [3553, 6187, 6323, 6362, 6394, 6640, 6735];
foreach ($ids as $id) {
    $post = get_post($id);
    if (!$post) {
        echo "missing $id\n";
        continue;
    }
    $replacement = str_contains($post->post_name, 'cordura') ? $tlh5657 : $tlh5651;
    $next = rs_swap_kg_list($post->post_content, $replacement);
    if ($next === $post->post_content) {
        echo "unchanged {$post->post_name}\n";
        continue;
    }
    $updated = wp_update_post(['ID' => $id, 'post_content' => $next], true);
    echo is_wp_error($updated) ? $updated->get_error_message() . "\n" : "product {$post->post_name}\n";
}

$chapters = <<<'HTML'
<!-- rs-weight-chapters -->
<h2>Rozmiar szelek według wagi psa</h2>
<p>Producent w karcie TLH5651 nie przypisuje rozmiaru do kilogramów. Liczy się obwód klatki. Przy górze zakresu bierze się większy rozmiar. Rozmiaru 2XL nie ma.</p>
<table>
<thead><tr><th>Rozmiar</th><th>Zalecana klatka psa</th><th>Regulacja szelek</th></tr></thead>
<tbody>
<tr><td>XS</td><td>28–38 cm</td><td>33–43 cm</td></tr>
<tr><td>S</td><td>38–51 cm</td><td>43–56 cm</td></tr>
<tr><td>M</td><td>51–64 cm</td><td>56–69 cm</td></tr>
<tr><td>L</td><td>64–76 cm</td><td>69–81 cm</td></tr>
<tr><td>XL</td><td>76–102 cm</td><td>81–107 cm</td></tr>
</tbody>
</table>
<p>Cordura (TLH5657) ma inną klatkę: XS 33–42 cm, S 40–56 cm, M 52–65 cm, L 64–80 cm, XL 78–96 cm. Jak na karcie jest Cordura, użyj tej tabeli, nie tej powyżej.</p>
<p>Rozdziały są po wagach, bo tak szuka się szelek. Żadna z tych wag nie wybiera litery.</p>
<h2 id="do-5-kg">Szelki dla psa do 5 kg</h2>
<p>5 kg nie jest rozmiarem. XS to klatka 28–38 cm, S to 38–51 cm. Jeśli pomiar jest przy 38 cm, bierz S.</p>
<h2 id="do-10-kg">Szelki dla psa do 10 kg</h2>
<p>10 kg nie jest rozmiarem. S kończy się przy 51 cm klatki, M jest od 51 do 64 cm. Przy 51 cm bierz M.</p>
<h2 id="do-15-kg">Szelki dla psa do 15 kg</h2>
<p>15 kg nie jest rozmiarem. M to klatka 51–64 cm. Przy 64 cm bierz L (64–76 cm), nie dociskaj M. Model z regulacją w czterech punktach: <a href="/produkt/szelki-dla-psa-truelove-front-line-premium/">Front Line Premium</a>.</p>
<h2 id="do-20-kg">Szelki dla psa do 20 kg</h2>
<p>20 kg nie jest rozmiarem i nie oznacza ani M, ani L. M to klatka 51–64 cm, L to 64–76 cm. Literę wskazuje miarka.</p>
<h2 id="do-30-kg">Szelki dla psa do 30 kg</h2>
<p>30 kg nie jest rozmiarem. L to klatka 64–76 cm, XL to 76–102 cm. Przy 76 cm bierz XL.</p>
<h2 id="do-50-kg">Szelki dla psa do 50 kg</h2>
<p>50 kg nie jest rozmiarem 2XL. Producent tego modelu nie ma 2XL. XL obejmuje klatkę 76–102 cm. Jeśli pomiar jest wyższy, większej litery w tej karcie nie ma. <a href="/jak-wybrac-szelki-dla-duzego-psa/">Jak wybrać szelki dla dużego psa</a>. Modele: <a href="/kategoria-produktu/szelki/">szelki Truelove</a>.</p>
HTML;

$post = get_post(5820);
$start = strpos($post->post_content, '<!-- rs-weight-chapters -->');
$end = strpos($post->post_content, '<h2>Przygotuj psa do pomiaru</h2>');
if ($start === false || $end === false || $end <= $start) {
    fwrite(STDERR, "guide markers missing\n");
    exit(1);
}
$content = substr($post->post_content, 0, $start) . $chapters . "\n" . substr($post->post_content, $end);
$updated = wp_update_post(['ID' => 5820, 'post_content' => $content], true);
echo is_wp_error($updated) ? $updated->get_error_message() . "\n" : "guide_replaced\n";

global $wpdb;
$meta = 'Jak dobrać rozmiar szelek według producenta TLH5651: obwód klatki, bez kilogramów. Przy górze zakresu większy rozmiar.';
$aioseo = $wpdb->get_row("SELECT id FROM {$wpdb->prefix}aioseo_posts WHERE post_id = 5820");
if ($aioseo) {
    $wpdb->update($wpdb->prefix . 'aioseo_posts', ['description' => $meta], ['id' => $aioseo->id]);
    echo "meta\n";
}
echo "done\n";
