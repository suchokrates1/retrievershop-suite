<?php
/** Ustaw SKU rodzica variable = pierwsze niepuste SKU wariantu. */
require '/var/www/html/wp-load.php';
header('Content-Type: text/plain; charset=utf-8');
$n = 0;
$q = new WP_Query([
    'post_type' => 'product',
    'post_status' => 'publish',
    'posts_per_page' => -1,
    'fields' => 'ids',
]);
foreach ($q->posts as $pid) {
    $p = wc_get_product($pid);
    if (!$p || $p->get_type() !== 'variable') {
        continue;
    }
    if (trim((string) $p->get_sku()) !== '') {
        continue;
    }
    $sku = '';
    foreach ($p->get_children() as $vid) {
        $v = wc_get_product($vid);
        if ($v && trim((string) $v->get_sku()) !== '') {
            $sku = trim((string) $v->get_sku());
            break;
        }
    }
    if ($sku === '') {
        continue;
    }
    $p->set_sku($sku);
    $p->save();
    $n++;
    echo "sku #{$pid}={$sku}\n";
}
echo "updated={$n}\n";
