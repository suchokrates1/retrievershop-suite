<?php
/**
 * Sanitize remaining Woo parent titles: strip trailing size/color, fix typos.
 * Does not change slugs (avoid mass URL churn).
 */
require '/var/www/html/wp-load.php';
header('Content-Type: text/plain; charset=utf-8');

$sizes = ['XXS','XS','S','M','L','XL','XXL','2XL','3XL','4XL','Uniwersalny'];
$colors = [
    'czarny','czarna','czarne','biały','bialy','biała','biala','białe','biale',
    'czerwony','czerwona','czerwone','niebieski','niebieska','niebieskie',
    'zielony','zielona','zielone','żółty','zolty','żółte','zolte',
    'różowy','rozowy','różowe','rozowe','różowa','rozowa',
    'fioletowy','fioletowa','fioletowe','pomarańczowy','pomaranczowy',
    'pomarańczowa','pomaranczowa','pomarańczowe','pomaranczowe',
    'szary','szara','szare','granatowy','granatowa','granatowe',
    'limonkowy','limonkowa','limonkowe','turkusowy','turkusowa','turkusowe',
    'liliowy','liliowa','liliowe','beżowy','bezowy','beżowe','bezowe',
];

function rs_sanitize_title($name, $sizes, $colors) {
    $repl = [
        'Trelove' => 'Truelove', 'Truelve' => 'Truelove', 'Fronr' => 'Front',
        'ptemium' => 'Premium', 'Ptemium' => 'Premium', 'średnieho' => 'średniego',
    ];
    foreach ($repl as $b => $g) {
        $name = str_replace($b, $g, $name);
    }
    // Drop "Szelki guard dla X psa" noise → keep brand/model if possible
    $name = preg_replace('/^Szelki guard dla (małego|średniego|dużego) psa\s+/iu', 'Szelki dla psa ', $name);
    $tokens = preg_split('/\s+/u', trim($name));
    while ($tokens) {
        $last = end($tokens);
        $last_l = mb_strtolower(rtrim($last, '.,;'));
        $is_size = false;
        foreach ($sizes as $s) {
            if (strcasecmp($last_l, mb_strtolower($s)) === 0) {
                $is_size = true;
                break;
            }
        }
        if ($is_size || in_array($last_l, $colors, true)) {
            array_pop($tokens);
            continue;
        }
        break;
    }
    return trim(implode(' ', $tokens), " -");
}

$ids = get_posts(['post_type' => 'product', 'post_status' => 'publish', 'posts_per_page' => -1, 'fields' => 'ids']);
$n = 0;
foreach ($ids as $id) {
    $p = wc_get_product($id);
    if (!$p) {
        continue;
    }
    $old = $p->get_name();
    $new = rs_sanitize_title($old, $sizes, $colors);
    if ($new !== '' && $new !== $old) {
        $p->set_name($new);
        $p->save();
        echo "#{$id}: {$old} => {$new}\n";
        $n++;
    }
}
echo "renamed={$n}\n";
